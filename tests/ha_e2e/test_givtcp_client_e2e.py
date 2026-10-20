"""The GivTCP client's controls, schedules and timed force over givtcp_mock in a real Home Assistant.

The mock publishes the entities with their options and limits and rejects a write outside them,
as Home Assistant does, so these tests also show the client never sends one.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest
from conftest import SERIAL
from givtcp_mock import MockGivTCP, Readings

from custom_components.givenergy_inverter_manager.inverter.givtcp import GivTCPPorts, make_backend
from custom_components.givenergy_inverter_manager.lib.givtcp import BatteryPause, Force, SlotKind
from custom_components.givenergy_inverter_manager.lib.givtcp.writer import GivTCPWriter

CFG = {"inverter_serial": SERIAL}


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


def _client(hass, *, time_entities: bool = False):
    mock = MockGivTCP(hass, serial=SERIAL)
    mock.publish(Readings())
    mock.add_client_controls(pause_as_time_entities=time_entities)
    mock.install()
    backend = make_backend(
        CFG,
        GivTCPPorts(
            get_state=hass.states.get,
            call_service=lambda domain, service, data: hass.services.async_call(
                domain, service, data, blocking=True
            ),
            on_count_change=lambda count: None,
        ),
    )
    return mock, backend


def _state(hass, mock, domain, suffix):
    return hass.states.get(mock.entity(domain, suffix)).state


# ── Pause, mode, reserve, rates, clock ────────────────────────────────────────


async def test_a_pause_writes_the_window_then_the_mode_and_ending_it_writes_the_mode(hass):
    mock, backend = _client(hass)

    assert await backend.apply_battery_pause(CFG, BatteryPause.BOTH, time(23, 30), time(5, 30))
    assert [w.entity_id.split(f"{mock.prefix}_")[1] for w in mock.writes] == [
        "battery_pause_start_time_slot",
        "battery_pause_end_time_slot",
        "battery_pause_mode",
    ]
    assert _state(hass, mock, "select", "battery_pause_mode") == "PauseBoth"
    assert _state(hass, mock, "select", "battery_pause_start_time_slot") == "23:30:00"

    mock.clear()
    assert await backend.apply_battery_pause(CFG, BatteryPause.OFF)
    assert mock.sequence() == [
        ("select.select_option", mock.entity("select", "battery_pause_mode"), "Disabled")
    ]


async def test_a_pause_window_is_written_to_time_entities_when_that_is_what_is_published(hass):
    mock, backend = _client(hass, time_entities=True)

    assert await backend.apply_battery_pause(CFG, BatteryPause.DISCHARGE, time(1, 0), time(2, 0))

    assert mock.writes[0].action == "time.set_value"
    assert _state(hass, mock, "time", "battery_pause_start_time_slot") == "01:00:00"


async def test_a_pause_time_the_drop_down_cannot_hold_is_refused_before_it_is_sent(hass):
    mock, backend = _client(hass)

    assert not await backend.apply_battery_pause(CFG, BatteryPause.DISCHARGE, time(1, 7), time(2))
    assert mock.writes == []


async def test_mode_reserve_and_rates_are_written_inside_the_limits(hass):
    mock, backend = _client(hass)

    assert await backend.apply_battery_mode(CFG, "timed demand")
    assert await backend.apply_reserve(CFG, 1)
    assert await backend.apply_charge_rate(CFG, 99_999)
    assert await backend.apply_discharge_rate(CFG, 1500)

    assert _state(hass, mock, "select", "mode") == "Timed Demand"
    assert _state(hass, mock, "number", "battery_power_reserve") == "4"
    assert _state(hass, mock, "number", "battery_charge_rate") == "2600"
    assert backend.read_discharge_rate(CFG) == 1500
    assert mock.other_calls == []


async def test_the_clock_skew_is_read_from_the_published_clock(hass):
    mock, backend = _client(hass)
    mock.set_clock("2031-03-04 12:05:00")

    assert backend.clock_skew_s(CFG, datetime(2031, 3, 4, 12, 0, 0)) == 300.0


# ── The discharge schedule and the extra charge slots ─────────────────────────


async def test_a_discharge_plan_ends_with_the_schedule_switch(hass):
    mock, backend = _client(hass)

    assert await backend.schedules.apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert [w.entity_id.split(f"{mock.prefix}_")[1] for w in mock.writes] == [
        "discharge_target_soc_1",
        "discharge_start_time_slot_1",
        "discharge_end_time_slot_1",
        "enable_discharge_schedule",
    ]
    assert backend.schedules.discharge_schedule_enabled(CFG) is True
    assert backend.schedules.read_slot(CFG, SlotKind.DISCHARGE) == ("17:00", "19:30")
    assert backend.schedules.read_discharge_target(CFG) == 30


async def test_a_rejected_window_write_leaves_the_schedule_off(hass):
    mock, backend = _client(hass)
    mock.fail_on(mock.entity("select", "discharge_end_time_slot_1"))

    assert not await backend.schedules.apply_discharge_plan(CFG, (time(17, 0), time(19, 30)), 30)

    assert backend.schedules.discharge_schedule_enabled(CFG) is False
    assert await backend.schedules.stop_discharge(CFG)


async def test_charge_slot_five_can_be_set_and_cleared_and_slot_eleven_does_not_exist(hass):
    mock, backend = _client(hass)

    assert await backend.schedules.apply_slot(CFG, SlotKind.CHARGE, 5, (time(12, 0), time(13, 15)))
    assert backend.schedules.read_slot(CFG, SlotKind.CHARGE, 5) == ("12:00", "13:15")
    assert await backend.schedules.clear_slot(CFG, SlotKind.CHARGE, 5)
    assert backend.schedules.read_slot(CFG, SlotKind.CHARGE, 5) == ("00:00", "00:00")
    assert not await backend.schedules.apply_slot(CFG, SlotKind.CHARGE, 11, (time(1), time(2)))


# ── Timed force ───────────────────────────────────────────────────────────────


async def test_a_force_uses_a_preset_the_select_lists_and_cancels_with_normal(hass):
    mock, backend = _client(hass)

    assert await backend.force.start(CFG, Force.EXPORT, 100)
    assert _state(hass, mock, "select", "force_export") == "1 hour"
    assert await backend.force.cancel(CFG, Force.EXPORT)
    assert _state(hass, mock, "select", "force_export") == "Normal"


async def test_a_force_longer_than_every_preset_goes_to_the_minutes_entity(hass):
    mock, backend = _client(hass)

    assert await backend.force.start(CFG, Force.CHARGE, 200)

    assert _state(hass, mock, "number", "force_charge_num") == "200"
    assert _state(hass, mock, "select", "force_charge") == "Normal"

