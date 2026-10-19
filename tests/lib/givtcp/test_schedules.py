"""The discharge schedule, the extra charge slots and the timed force."""

from __future__ import annotations

import asyncio
from datetime import time
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.inverter.backend import (
    InverterBackend,
    InverterControls,
)
from custom_components.givenergy_inverter_manager.lib.givtcp import (
    Force,
    GivTCPPorts,
    GivTCPSchedules,
    SlotKind,
    make_backend,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.force import option_minutes
from custom_components.givenergy_inverter_manager.lib.givtcp.keys import KEY_INVERTER_SERIAL
from custom_components.givenergy_inverter_manager.lib.givtcp.status import WriteStatus

PREFIX = "givtcp_sa1"
CFG = {KEY_INVERTER_SERIAL: "SA1", "target_soc_entity": f"number.{PREFIX}_target_soc"}
TIMES = [f"{h:02d}:{m:02d}:00" for h in range(24) for m in (0, 30)]
SCHEDULE = f"switch.{PREFIX}_enable_discharge_schedule"
D_START = f"select.{PREFIX}_discharge_start_time_slot_1"
D_END = f"select.{PREFIX}_discharge_end_time_slot_1"
D_TARGET = f"number.{PREFIX}_discharge_target_soc_1"
C2_START = f"select.{PREFIX}_charge_start_time_slot_2"
C2_END = f"select.{PREFIX}_charge_end_time_slot_2"
FORCE_EXPORT = f"select.{PREFIX}_force_export"
FORCE_EXPORT_NUM = f"number.{PREFIX}_force_export_num"
FORCE_CHARGE = f"select.{PREFIX}_force_charge"


def _state(value, **attributes):
    return SimpleNamespace(state=str(value), attributes=attributes)


class _Bus:
    def __init__(self, states: dict) -> None:
        self.states = dict(states)
        self.calls: list[tuple[str, str, dict]] = []
        self.refuse: set[str] = set()

    def get_state(self, entity_id: str):
        return self.states.get(entity_id)

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        self.calls.append((domain, service, data))
        if data["entity_id"] in self.refuse:
            return
        old = self.states[data["entity_id"]]
        value = {"turn_on": "on", "turn_off": "off"}.get(
            service, data.get("option", data.get("value", data.get("time")))
        )
        self.states[data["entity_id"]] = _state(value, **old.attributes)

    @property
    def written(self) -> list[tuple[str, object]]:
        return [
            (
                c[2]["entity_id"],
                {"turn_on": "on", "turn_off": "off"}.get(
                    c[1], c[2].get("option", c[2].get("value", c[2].get("time")))
                ),
            )
            for c in self.calls
        ]


def _bus(**overrides) -> _Bus:
    states = {
        SCHEDULE: _state("off"),
        D_START: _state("00:00:00", options=TIMES),
        D_END: _state("00:00:00", options=TIMES),
        D_TARGET: _state(20, min=4, max=100),
        C2_START: _state("00:00:00", options=TIMES),
        C2_END: _state("00:00:00", options=TIMES),
        FORCE_EXPORT: _state("Normal", options=["Normal", "15 minutes", "30 minutes", "1 hour", "2 hours"]),
        FORCE_EXPORT_NUM: _state(0, min=0, max=240),
        FORCE_CHARGE: _state("Normal", options=["Normal", "30", "60"]),
    }
    states.update(overrides)
    return _Bus(states)


@pytest.fixture(autouse=True)
def _no_read_back_wait(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _backend(bus: _Bus):
    return make_backend(CFG, GivTCPPorts(bus.get_state, bus.call_service, lambda count: None))


def test_the_export_writes_are_on_the_client_and_in_none_of_the_integrations_interfaces():
    backend = _backend(_bus())
    integration = {
        name
        for protocol in (InverterBackend, InverterControls)
        for name in dir(protocol)
        if not name.startswith("_")
    }

    assert backend.schedules.apply_discharge_plan
    assert backend.force.start
    for name in ("apply_discharge_plan", "stop_discharge", "start_force", "apply_slot", "start"):
        assert name not in integration
    assert not hasattr(backend, "apply_discharge_plan")


# ── The discharge schedule ────────────────────────────────────────────────────


async def test_a_discharge_plan_sets_the_target_and_window_before_it_switches_on():
    bus = _bus()

    taken = await _backend(bus).schedules.apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert taken
    assert bus.written == [
        (D_TARGET, 30),
        (D_START, "17:00:00"),
        (D_END, "19:30:00"),
        (SCHEDULE, "on"),
    ]


async def test_a_failed_write_stops_the_plan_before_the_schedule_is_switched_on():
    bus = _bus()
    bus.states.pop(D_END)

    taken = await _backend(bus).schedules.apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert not (taken)
    assert (SCHEDULE, "on") not in bus.written
    assert bus.states[SCHEDULE].state == "off"


async def test_stopping_a_discharge_writes_the_switch_only():
    bus = _bus(**{SCHEDULE: _state("on")})

    assert await _backend(bus).schedules.stop_discharge(CFG)

    assert bus.written == [(SCHEDULE, "off")]


@pytest.mark.parametrize(("asked", "sent"), [(50, 50), (0, 4), (200, 100)])
async def test_the_discharge_target_is_kept_inside_the_limits(asked, sent):
    bus = _bus()

    await _backend(bus).schedules.apply_discharge_plan(CFG, (time(1, 0), time(2, 0)), asked)

    assert bus.written[0] == (D_TARGET, sent)


async def test_an_empty_discharge_window_is_refused_and_nothing_is_sent():
    bus = _bus()

    assert not (await _backend(bus).schedules.apply_discharge_plan(CFG, (time(5, 0), time(5, 0)), 20))
    assert (SCHEDULE, "on") not in bus.written


def test_the_schedule_the_window_and_the_target_are_read():
    bus = _bus(
        **{
            SCHEDULE: _state("on"),
            D_START: _state("17:00:00", options=TIMES),
            D_END: _state("19:30:00", options=TIMES),
            D_TARGET: _state(25, min=4, max=100),
        }
    )
    backend = _backend(bus)

    assert backend.schedules.discharge_schedule_enabled(CFG)
    assert backend.schedules.read_slot(CFG, SlotKind.DISCHARGE) == ("17:00", "19:30")
    assert backend.schedules.read_discharge_target(CFG) == 25


def test_a_schedule_switch_that_is_not_published_reads_as_unknown_not_off():
    backend = _backend(_Bus({}))

    assert backend.schedules.discharge_schedule_enabled(CFG) is None
    assert backend.schedules.read_slot(CFG, SlotKind.DISCHARGE) is None
    assert backend.schedules.read_discharge_target(CFG) is None


@pytest.mark.parametrize("slot", [0, 11, -1])
async def test_a_slot_outside_one_to_ten_is_refused(slot):
    bus = _bus()

    assert not (await _backend(bus).schedules.apply_slot(CFG, SlotKind.DISCHARGE, slot, (time(1), time(2))))
    assert bus.calls == []


# ── Charge slots from 2 up ────────────────────────────────────────────────────


async def test_charge_slot_two_can_be_written_and_cleared():
    bus = _bus()
    backend = _backend(bus)

    assert await backend.schedules.apply_slot(CFG, SlotKind.CHARGE, 2, (time(12, 0), time(14, 30)))
    assert await backend.schedules.clear_slot(CFG, SlotKind.CHARGE, 2)

    assert bus.states[C2_START].state == "00:00:00"
    assert bus.states[C2_END].state == "00:00:00"
    assert sorted(bus.written[:2]) == [(C2_END, "14:30:00"), (C2_START, "12:00:00")]


def _slot_bus(start: str, end: str) -> _Bus:
    return _bus(**{C2_START: _state(start, options=TIMES), C2_END: _state(end, options=TIMES)})


@pytest.mark.parametrize(
    ("current", "new", "first"),
    [
        (("01:00:00", "02:00:00"), (time(3, 0), time(4, 0)), C2_END),  # later: end first
        (("03:00:00", "04:00:00"), (time(1, 0), time(2, 0)), C2_START),  # earlier: start first
        (("23:00:00", "23:30:00"), (time(0, 30), time(1, 0)), C2_END),  # later, across midnight
        (("00:30:00", "01:00:00"), (time(23, 0), time(23, 30)), C2_START),  # earlier, across it
    ],
)
async def test_a_window_is_written_so_the_inverter_never_holds_a_gap(current, new, first):
    bus = _slot_bus(*current)

    assert await _backend(bus).schedules.apply_slot(CFG, SlotKind.CHARGE, 2, new)

    assert bus.written[0][0] == first
    assert bus.states[C2_START].state == new[0].strftime("%H:%M:%S")
    assert bus.states[C2_END].state == new[1].strftime("%H:%M:%S")


async def test_a_window_whose_start_does_not_move_only_writes_the_end():
    bus = _slot_bus("01:00:00", "02:00:00")

    assert await _backend(bus).schedules.apply_slot(CFG, SlotKind.CHARGE, 2, (time(1, 0), time(3, 0)))

    assert bus.written == [(C2_END, "03:00:00")]


async def test_a_window_whose_current_start_is_unreadable_is_written_start_first():
    bus = _slot_bus("unknown", "02:00:00")

    assert await _backend(bus).schedules.apply_slot(CFG, SlotKind.CHARGE, 2, (time(3, 0), time(4, 0)))

    assert bus.written[0][0] == C2_START


async def test_a_window_with_one_end_the_select_cannot_hold_sends_nothing():
    bus = _bus(**{C2_START: _state("01:00:00", options=TIMES), C2_END: _state("02:00:00", options=["02:00:00"])})

    status = await _backend(bus).schedules.apply_slot(CFG, SlotKind.CHARGE, 2, (time(3, 0), time(4, 0)))

    assert status is WriteStatus.REFUSED
    assert bus.calls == []


# ── Timed force ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("30 minutes", 30), ("1 hour", 60), ("2 hrs", 120), ("90", 90), ("1.5 hours", 90), ("Normal", None)],
)
def test_a_preset_is_read_as_minutes(text, minutes):
    assert option_minutes(text) == minutes


async def test_a_force_export_uses_the_longest_preset_that_is_not_longer_than_asked():
    bus = _bus()

    assert await _backend(bus).force.start(CFG, Force.EXPORT, 100)

    assert bus.written == [(FORCE_EXPORT, "1 hour")]


async def test_a_force_longer_than_every_preset_goes_to_the_minutes_entity():
    bus = _bus()

    assert await _backend(bus).force.start(CFG, Force.EXPORT, 200)

    assert bus.written == [(FORCE_EXPORT_NUM, 200)]


async def test_a_force_beyond_the_minutes_limit_falls_back_to_the_longest_preset_that_fits():
    bus = _bus(**{FORCE_EXPORT: _state("Normal", options=["Normal", "30 minutes"])})

    assert await _backend(bus).force.start(CFG, Force.EXPORT, 300)

    assert bus.written == [(FORCE_EXPORT, "30 minutes")]


async def test_a_force_shorter_than_every_preset_is_refused_so_it_is_never_longer_than_asked():
    bus = _bus(**{FORCE_EXPORT_NUM: _state(0, min=0, max=0)})

    assert not (await _backend(bus).force.start(CFG, Force.EXPORT, 5))
    assert bus.calls == []


@pytest.mark.parametrize("minutes", [0, -10])
async def test_a_force_of_no_time_is_refused(minutes):
    bus = _bus()

    assert not (await _backend(bus).force.start(CFG, Force.CHARGE, minutes))
    assert bus.calls == []


async def test_a_force_is_cancelled_with_the_presets_own_normal_option():
    bus = _bus(**{FORCE_CHARGE: _state("60", options=["Normal", "30", "60"])})

    assert await _backend(bus).force.cancel(CFG, Force.CHARGE)

    assert bus.written == [(FORCE_CHARGE, "Normal")]


async def test_a_force_with_no_cancel_option_is_cancelled_through_the_minutes_entity():
    bus = _bus(
        **{
            FORCE_EXPORT: _state("30 minutes", options=["15 minutes", "30 minutes"]),
            FORCE_EXPORT_NUM: _state(60, min=0, max=240),
        }
    )

    assert await _backend(bus).force.cancel(CFG, Force.EXPORT)

    assert bus.written == [(FORCE_EXPORT_NUM, 0)]


async def test_force_on_a_device_that_publishes_nothing_is_refused():
    bus = _Bus({})
    backend = _backend(bus)

    assert not (await backend.force.start(CFG, Force.CHARGE, 30))
    assert not (await backend.force.cancel(CFG, Force.CHARGE))
    assert bus.calls == []


def _schedules(bus: _Bus) -> GivTCPSchedules:
    return GivTCPSchedules(_backend(bus).writer, bus.get_state)


async def test_stopping_a_discharge_is_refused_when_the_switch_cannot_be_read():
    bus = _bus(**{SCHEDULE: _state("unavailable")})

    status = await _backend(bus).schedules.stop_discharge(CFG)

    assert status is WriteStatus.REFUSED
    assert bus.calls == []


async def test_a_schedule_switch_the_device_does_not_publish_is_refused_without_a_call():
    bus = _bus()
    del bus.states[SCHEDULE]

    assert await _schedules(bus).set_discharge_schedule(CFG, enabled=True) is WriteStatus.REFUSED
    assert bus.calls == []


async def test_a_reserve_for_a_missing_entity_sends_nothing():
    bus = _bus()

    assert not await _backend(bus).apply_reserve(CFG, 20)
    assert bus.calls == []


async def test_a_force_started_cancelled_and_started_again_is_sent_the_third_time():
    bus = _bus()
    backend = _backend(bus)
    on = await backend.force.start(CFG, Force.EXPORT, 30)
    off = await backend.force.cancel(CFG, Force.EXPORT)
    again = await backend.force.start(CFG, Force.EXPORT, 30)

    assert (on, off, again) == (WriteStatus.WRITTEN,) * 3
    assert bus.states[FORCE_EXPORT].state == "30 minutes"


async def test_a_write_that_never_reads_back_is_unconfirmed_and_can_be_tried_again():
    bus = _bus()
    bus.refuse.add(SCHEDULE)
    schedules = _schedules(bus)

    first = await schedules.set_discharge_schedule(CFG, enabled=True)
    bus.refuse.clear()
    second = await schedules.set_discharge_schedule(CFG, enabled=True)

    assert (first, second) == (WriteStatus.UNCONFIRMED, WriteStatus.WRITTEN)
