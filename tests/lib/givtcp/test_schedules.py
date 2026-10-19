"""The discharge schedule, the extra charge slots and the timed force."""

from __future__ import annotations

import asyncio
from datetime import time
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.inverter.backend import InverterExport
from custom_components.givenergy_inverter_manager.lib.givtcp import (
    Force,
    GivTCPPorts,
    SlotKind,
    make_backend,
    option_minutes,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.keys import KEY_INVERTER_SERIAL

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


def test_the_adapter_offers_the_export_interface():
    assert isinstance(_backend(_bus()), InverterExport)


# ── The discharge schedule ────────────────────────────────────────────────────


async def test_a_discharge_plan_sets_the_target_and_window_before_it_switches_on():
    bus = _bus()

    taken = await _backend(bus).apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert taken is True
    assert bus.written == [
        (D_TARGET, 30),
        (D_START, "17:00:00"),
        (D_END, "19:30:00"),
        (SCHEDULE, "on"),
    ]


async def test_a_failed_write_stops_the_plan_before_the_schedule_is_switched_on():
    bus = _bus()
    bus.states.pop(D_END)

    taken = await _backend(bus).apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert taken is False
    assert (SCHEDULE, "on") not in bus.written
    assert bus.states[SCHEDULE].state == "off"


async def test_stopping_a_discharge_writes_the_switch_only():
    bus = _bus(**{SCHEDULE: _state("on")})

    assert await _backend(bus).stop_discharge(CFG) is True

    assert bus.written == [(SCHEDULE, "off")]


@pytest.mark.parametrize(("asked", "sent"), [(50, 50), (0, 4), (200, 100)])
async def test_the_discharge_target_is_kept_inside_the_limits(asked, sent):
    bus = _bus()

    await _backend(bus).apply_discharge_plan(CFG, (time(1, 0), time(2, 0)), asked)

    assert bus.written[0] == (D_TARGET, sent)


async def test_an_empty_discharge_window_is_refused_and_nothing_is_sent():
    bus = _bus()

    assert await _backend(bus).apply_discharge_plan(CFG, (time(5, 0), time(5, 0)), 20) is False
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

    assert backend.discharge_schedule_enabled(CFG) is True
    assert backend.read_slot(CFG, SlotKind.DISCHARGE) == ("17:00", "19:30")
    assert backend.read_discharge_target(CFG) == 25


def test_a_schedule_switch_that_is_not_published_reads_as_unknown_not_off():
    backend = _backend(_Bus({}))

    assert backend.discharge_schedule_enabled(CFG) is None
    assert backend.read_slot(CFG, SlotKind.DISCHARGE) is None
    assert backend.read_discharge_target(CFG) is None


@pytest.mark.parametrize("slot", [0, 11, -1])
async def test_a_slot_outside_one_to_ten_is_refused(slot):
    bus = _bus()

    assert await _backend(bus).apply_slot(CFG, SlotKind.DISCHARGE, slot, (time(1), time(2))) is False
    assert bus.calls == []


# ── Charge slots from 2 up ────────────────────────────────────────────────────


async def test_charge_slot_two_is_written_start_then_end_and_can_be_cleared():
    bus = _bus()
    backend = _backend(bus)

    assert await backend.apply_slot(CFG, SlotKind.CHARGE, 2, (time(12, 0), time(14, 30))) is True
    assert await backend.clear_slot(CFG, SlotKind.CHARGE, 2) is True

    assert bus.written == [
        (C2_START, "12:00:00"),
        (C2_END, "14:30:00"),
        (C2_START, "00:00:00"),
        (C2_END, "00:00:00"),
    ]


# ── Timed force ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("30 minutes", 30), ("1 hour", 60), ("2 hrs", 120), ("90", 90), ("1.5 hours", 90), ("Normal", None)],
)
def test_a_preset_is_read_as_minutes(text, minutes):
    assert option_minutes(text) == minutes


async def test_a_force_export_uses_the_longest_preset_that_is_not_longer_than_asked():
    bus = _bus()

    assert await _backend(bus).start_force(CFG, Force.EXPORT, 100) is True

    assert bus.written == [(FORCE_EXPORT, "1 hour")]


async def test_a_force_longer_than_every_preset_goes_to_the_minutes_entity():
    bus = _bus()

    assert await _backend(bus).start_force(CFG, Force.EXPORT, 200) is True

    assert bus.written == [(FORCE_EXPORT_NUM, 200)]


async def test_a_force_beyond_the_minutes_limit_falls_back_to_the_longest_preset_that_fits():
    bus = _bus(**{FORCE_EXPORT: _state("Normal", options=["Normal", "30 minutes"])})

    assert await _backend(bus).start_force(CFG, Force.EXPORT, 300) is True

    assert bus.written == [(FORCE_EXPORT, "30 minutes")]


async def test_a_force_shorter_than_every_preset_is_refused_so_it_is_never_longer_than_asked():
    bus = _bus(**{FORCE_EXPORT_NUM: _state(0, min=0, max=0)})

    assert await _backend(bus).start_force(CFG, Force.EXPORT, 5) is False
    assert bus.calls == []


@pytest.mark.parametrize("minutes", [0, -10])
async def test_a_force_of_no_time_is_refused(minutes):
    bus = _bus()

    assert await _backend(bus).start_force(CFG, Force.CHARGE, minutes) is False
    assert bus.calls == []


async def test_a_force_is_cancelled_with_the_presets_own_normal_option():
    bus = _bus(**{FORCE_CHARGE: _state("60", options=["Normal", "30", "60"])})

    assert await _backend(bus).cancel_force(CFG, Force.CHARGE) is True

    assert bus.written == [(FORCE_CHARGE, "Normal")]


async def test_a_force_with_no_cancel_option_is_cancelled_through_the_minutes_entity():
    bus = _bus(
        **{
            FORCE_EXPORT: _state("30 minutes", options=["15 minutes", "30 minutes"]),
            FORCE_EXPORT_NUM: _state(60, min=0, max=240),
        }
    )

    assert await _backend(bus).cancel_force(CFG, Force.EXPORT) is True

    assert bus.written == [(FORCE_EXPORT_NUM, 0)]


async def test_force_on_a_device_that_publishes_nothing_is_refused():
    bus = _Bus({})
    backend = _backend(bus)

    assert await backend.start_force(CFG, Force.CHARGE, 30) is False
    assert await backend.cancel_force(CFG, Force.CHARGE) is False
    assert bus.calls == []
