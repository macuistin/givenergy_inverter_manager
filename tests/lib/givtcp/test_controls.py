"""The settings beside the charge write: pause, mode, reserve, rates and the inverter clock."""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp import (
    BatteryPause,
    GivTCPPorts,
    controls,
    make_backend,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.keys import KEY_INVERTER_SERIAL

PREFIX = "givtcp_sa1"
CFG = {KEY_INVERTER_SERIAL: "SA1", "target_soc_entity": f"number.{PREFIX}_target_soc"}
MODE = f"select.{PREFIX}_battery_pause_mode"
START = f"select.{PREFIX}_battery_pause_start_time_slot"
END = f"select.{PREFIX}_battery_pause_end_time_slot"
BATTERY_MODE = f"select.{PREFIX}_mode"
RESERVE = f"number.{PREFIX}_battery_power_reserve"
CHARGE_RATE = f"number.{PREFIX}_battery_charge_rate"
DISCHARGE_RATE = f"number.{PREFIX}_battery_discharge_rate"
CLOCK = f"sensor.{PREFIX}_invertor_time"

PAUSE_OPTIONS = ["Disabled", "PauseCharge", "PauseDischarge", "PauseBoth"]
TIMES = [f"{h:02d}:{m:02d}:00" for h in range(24) for m in (0, 30)]


def _state(value, **attributes):
    return SimpleNamespace(state=str(value), attributes=attributes)


class _Bus:
    """States that follow a write, with every call recorded."""

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
        value = data.get("option", data.get("value", data.get("time")))
        self.states[data["entity_id"]] = _state(value, **old.attributes)

    @property
    def written(self) -> list[tuple[str, object]]:
        return [(c[2]["entity_id"], c[2].get("option", c[2].get("value", c[2].get("time")))) for c in self.calls]


def _pause_bus(**overrides) -> _Bus:
    states = {
        MODE: _state("Disabled", options=PAUSE_OPTIONS),
        START: _state("00:00:00", options=TIMES),
        END: _state("00:00:00", options=TIMES),
        BATTERY_MODE: _state("Eco", options=["Eco", "Timed Demand", "Timed Export"]),
        RESERVE: _state(20, min=4, max=100),
        CHARGE_RATE: _state(2600, min=0, max=3000),
        DISCHARGE_RATE: _state(2600, min=0, max=3000),
        CLOCK: _state("2031-03-04 12:00:30"),
    }
    states.update(overrides)
    return _Bus(states)


@pytest.fixture(autouse=True)
def _no_read_back_wait(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _backend(bus: _Bus):
    ports = GivTCPPorts(bus.get_state, bus.call_service, lambda count: None)
    return make_backend(CFG, ports)


# ── The battery pause ─────────────────────────────────────────────────────────


async def test_pausing_discharge_writes_the_window_before_the_mode():
    bus = _pause_bus()

    taken = await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.DISCHARGE, time(23, 30), time(5, 30)
    )

    assert taken
    assert bus.written == [(START, "23:30:00"), (END, "05:30:00"), (MODE, "PauseDischarge")]


async def test_ending_a_pause_writes_the_mode_only():
    bus = _pause_bus(**{MODE: _state("PauseDischarge", options=PAUSE_OPTIONS)})

    assert await _backend(bus).apply_battery_pause(CFG, BatteryPause.OFF)

    assert bus.written == [(MODE, "Disabled")]


async def test_an_install_that_spells_the_options_with_spaces_is_sent_its_own_spelling():
    options = ["Not Paused", "Pause Charge", "Pause Discharge", "Pause Both"]
    bus = _pause_bus(**{MODE: _state("Pause Discharge", options=options)})

    assert await _backend(bus).apply_battery_pause(CFG, BatteryPause.OFF)

    assert bus.written == [(MODE, "Not Paused")]


async def test_a_pause_option_the_entity_does_not_offer_is_refused_and_nothing_is_sent():
    bus = _pause_bus(**{MODE: _state("Disabled", options=["Disabled", "PauseCharge"])})

    taken = await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.DISCHARGE, time(23, 30), time(5, 30)
    )

    assert not (taken)
    assert bus.calls == []


@pytest.mark.parametrize(("start", "end"), [(None, time(5, 0)), (time(5, 0), None), (time(5, 0), time(5, 0))])
async def test_a_pause_without_a_usable_window_is_refused_and_nothing_is_sent(start, end):
    bus = _pause_bus()

    taken = await _backend(bus).apply_battery_pause(CFG, BatteryPause.BOTH, start, end)

    assert not (taken)
    assert bus.calls == []


async def test_a_pause_on_a_device_that_publishes_no_pause_entities_is_refused():
    bus = _Bus({})

    assert not (await _backend(bus).apply_battery_pause(CFG, BatteryPause.OFF))
    assert bus.calls == []


async def test_a_time_picker_is_written_with_the_time_service():
    start, end = f"time.{PREFIX}_battery_pause_start_time_slot", f"time.{PREFIX}_battery_pause_end_time_slot"
    bus = _pause_bus()
    del bus.states[START], bus.states[END]
    bus.states[start] = _state("00:00:00")
    bus.states[end] = _state("00:00:00")

    taken = await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.CHARGE, time(1, 0), time(2, 0)
    )

    assert taken
    assert [(c[0], c[1]) for c in bus.calls[:2]] == [("time", "set_value")] * 2
    assert bus.calls[0][2] == {"entity_id": start, "time": "01:00:00"}


async def test_a_window_the_drop_down_cannot_hold_is_refused():
    bus = _pause_bus(**{START: _state("00:00:00", options=["00:00:00", "00:30:00"])})

    taken = await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.DISCHARGE, time(0, 10), time(0, 30)
    )

    assert not (taken)
    assert bus.calls == []


async def test_a_pause_already_in_place_is_not_written_again():
    bus = _pause_bus(
        **{
            MODE: _state("PauseDischarge", options=PAUSE_OPTIONS),
            START: _state("23:30:00", options=TIMES),
            END: _state("05:30:00", options=TIMES),
        }
    )

    assert await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.DISCHARGE, time(23, 30), time(5, 30)
    )

    assert bus.calls == []


async def test_a_pause_that_does_not_take_is_still_reported_as_sent_like_other_writes():
    bus = _pause_bus()
    bus.refuse.add(MODE)

    taken = await _backend(bus).apply_battery_pause(
        CFG, BatteryPause.DISCHARGE, time(23, 30), time(5, 30)
    )

    assert taken
    assert bus.states[MODE].state == "Disabled"


# ── The battery mode ──────────────────────────────────────────────────────────


async def test_the_battery_mode_is_read_and_written():
    bus = _pause_bus()
    backend = _backend(bus)

    assert backend.read_battery_mode(CFG) == "Eco"
    assert await backend.apply_battery_mode(CFG, "timed demand")
    assert bus.written == [(BATTERY_MODE, "Timed Demand")]


async def test_an_export_mode_is_written_like_any_other_because_the_client_has_no_policy():
    bus = _pause_bus()

    assert await _backend(bus).apply_battery_mode(CFG, "timed export")
    assert bus.written == [(BATTERY_MODE, "Timed Export")]


async def test_an_unknown_mode_is_refused():
    bus = _pause_bus()

    assert not (await _backend(bus).apply_battery_mode(CFG, "Turbo"))
    assert bus.calls == []


@pytest.mark.parametrize("value", ["unavailable", "unknown"])
def test_a_mode_that_is_not_readable_reads_as_none(value):
    bus = _pause_bus(**{BATTERY_MODE: _state(value)})

    assert _backend(bus).read_battery_mode(CFG) is None


# ── Reserve and rates ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("asked", "sent"), [(50, 50), (0, 4), (150, 100)])
async def test_the_reserve_is_kept_inside_the_limits(asked, sent):
    bus = _pause_bus()

    await _backend(bus).apply_reserve(CFG, asked)

    assert bus.written == [(RESERVE, sent)]


async def test_the_reserve_follows_the_maximum_the_entity_publishes():
    bus = _pause_bus(**{RESERVE: _state(4, min=4, max=98)})

    await _backend(bus).apply_reserve(CFG, 100)

    assert bus.written == [(RESERVE, 98)]


@pytest.mark.parametrize(("asked", "sent"), [(1500, 1500), (-5, 0), (9000, 3000)])
async def test_the_rates_are_kept_inside_the_limits(asked, sent):
    bus = _pause_bus()
    backend = _backend(bus)

    await backend.apply_charge_rate(CFG, asked)
    await backend.apply_discharge_rate(CFG, asked)

    assert bus.written == [(CHARGE_RATE, sent), (DISCHARGE_RATE, sent)]


async def test_the_reserve_and_rates_are_read():
    backend = _backend(_pause_bus())

    assert (backend.read_reserve(CFG), backend.read_charge_rate(CFG)) == (20, 2600)
    assert backend.read_discharge_rate(CFG) == 2600


async def test_controls_that_are_missing_are_not_written():
    bus = _Bus({})
    backend = _backend(bus)

    assert await backend.apply_reserve(CFG, 10) is False or bus.calls == []
    assert backend.read_reserve(CFG) is None
    assert backend.read_charge_rate(CFG) is None


# ── The inverter clock ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "skew"),
    [
        ("2031-03-04 12:00:30", 30.0),
        ("2031-03-04T11:58:00", -120.0),
        ("04/03/2031 12:05:00", 300.0),
    ],
)
def test_the_clock_skew_is_the_inverter_minus_the_host(text, skew):
    bus = _pause_bus(**{CLOCK: _state(text)})

    assert _backend(bus).clock_skew_s(CFG, datetime(2031, 3, 4, 12, 0, 0)) == skew


def test_only_the_wall_clock_of_a_timezone_aware_host_time_is_compared():
    from datetime import timezone

    skew = _backend(_pause_bus()).clock_skew_s(CFG, datetime(2031, 3, 4, 12, 0, 0, tzinfo=timezone.utc))

    assert skew == 30.0


@pytest.mark.parametrize("value", ["unavailable", "unknown", "soon"])
def test_an_unreadable_clock_gives_no_skew(value):
    bus = _pause_bus(**{CLOCK: _state(value)})

    assert _backend(bus).clock_skew_s(CFG, datetime(2031, 3, 4, 12, 0, 0)) is None


def test_the_module_exports_what_the_adapter_uses():
    assert controls.BatteryPause is BatteryPause


def test_the_adapter_offers_every_control_the_interface_names():
    from custom_components.givenergy_inverter_manager.inverter.backend import InverterControls

    assert isinstance(_backend(_pause_bus()), InverterControls)


@pytest.mark.parametrize(
    ("mode", "discharge", "charge"),
    [("Not Paused", False, False), ("Pause Discharge", True, False), ("Pause Both", True, True)],
)
def test_the_spaced_pause_options_read_the_same_as_the_compact_ones(mode, discharge, charge):
    from custom_components.givenergy_inverter_manager.lib.givtcp import (
        pauses_charge,
        pauses_discharge,
    )

    assert (pauses_discharge(mode), pauses_charge(mode)) == (discharge, charge)
