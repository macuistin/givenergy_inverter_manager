"""A charge target worked out again inside the cheap window, against the mock GivTCP.

`givtcp_mock` records every command the device receives, so the assertions are on the
device side: which values were written, in which order, and that nothing outside the window was.
The night is 02:15 inside the 02:00 to 04:00 window, with the first write already sent.
"""

from __future__ import annotations

import pytest
from conftest import FORECAST, FORECAST_P10, SERIAL, Scenario
from givtcp_mock import MockGivTCP
from test_write_sequence_e2e import (
    ENABLE_TARGET,
    NIGHT,
    TARGET,
    WINDOW_END,
    WINDOW_START,
    _readings,
    _set_up,
    cycle,
)

from custom_components.givenergy_inverter_manager import const

# A summer night, 02:15 local time inside the 02:00 to 04:00 window. Winter and shoulder
# months have their own rules, so the forecast only moves the plan in the summer.
SUMMER_NIGHT = Scenario(
    name="summer_cheap_night",
    frozen_utc="2026-06-15 01:15:00+00:00",
    solar_w=0.0,
    battery_soc=31.0,
    battery_w=0.0,
    grid_w=-600.0,
    load_w=600.0,
)


@pytest.fixture
def scenario():
    return SUMMER_NIGHT


@pytest.fixture
def mock(hass_in_scenario, scenario) -> MockGivTCP:
    device = MockGivTCP(hass_in_scenario, serial=SERIAL)
    device.publish(_readings(scenario))
    device.install()
    return device

_ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy"}


@pytest.fixture
def night(mock: MockGivTCP):
    mock.publish(NIGHT)
    return NIGHT


async def _written_first_target(hass, mock, *, replan: bool, **options):
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            const.CONF_CHARGE_REPLAN: replan,
            const.CONF_OVERNIGHT_CHARGE_TARGET: 100,
            **options,
        },
    )
    await hass.async_block_till_done()
    mock.install()
    mock.clear()
    coordinator = entry.runtime_data
    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()
    assert [w.entity_id for w in mock.writes][-2:] == [TARGET, ENABLE_TARGET]
    return entry, coordinator


def _forecast(hass, kwh: float) -> None:
    hass.states.async_set(FORECAST, kwh, _ENERGY)
    hass.states.async_set(FORECAST_P10, kwh * 0.7, _ENERGY)


async def test_a_forecast_that_falls_mid_window_writes_only_the_new_target(
    hass_in_scenario, mock, night
):
    hass = hass_in_scenario
    entry, coordinator = await _written_first_target(hass, mock, replan=True)
    first = coordinator.data.charge_decision.target_soc
    mock.clear()
    coordinator._backend.writer.last_write_time.clear()

    _forecast(hass, 11.0)
    await cycle(hass, entry)

    new = coordinator.data.charge_decision.target_soc
    assert abs(new - first) >= const.REPLAN_MIN_CHANGE_PTS
    # The window and the enable switch already hold their values, so read-before-write sends the
    # target alone.
    assert new < 100
    assert mock.sequence() == [("number.set_value", TARGET, new)]
    assert hass.states.get(ENABLE_TARGET).state == "on"
    assert hass.states.get(TARGET).state == str(new)
    assert [w.entity_id for w in mock.writes if w.entity_id in (WINDOW_START, WINDOW_END)] == []
    assert mock.other_calls == []


async def test_a_target_of_a_hundred_turns_the_enable_switch_off(hass_in_scenario, mock, night):
    hass = hass_in_scenario
    entry, coordinator = await _written_first_target(hass, mock, replan=True)
    mock.clear()
    coordinator._backend.writer.last_write_time.clear()

    _forecast(hass, 0.0)
    await cycle(hass, entry)

    assert coordinator.data.charge_decision.target_soc == 100
    assert mock.sequence() == [
        ("number.set_value", TARGET, 100),
        ("switch.turn_off", ENABLE_TARGET, None),
    ]
    assert hass.states.get(TARGET).state == "100"
    assert hass.states.get(ENABLE_TARGET).state == "off"


async def test_with_the_switch_off_the_device_is_left_alone(hass_in_scenario, mock, night):
    hass = hass_in_scenario
    entry, coordinator = await _written_first_target(hass, mock, replan=False)
    mock.clear()
    coordinator._backend.writer.last_write_time.clear()

    _forecast(hass, 0.0)
    await cycle(hass, entry)

    assert mock.sequence() == []


async def test_dry_run_sends_nothing_and_says_what_it_would_do(hass_in_scenario, mock, night):
    hass = hass_in_scenario
    entry, coordinator = await _written_first_target(hass, mock, replan=True)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, const.CONF_DRY_RUN: True}
    )
    await hass.async_block_till_done()
    mock.clear()

    _forecast(hass, 0.0)
    await cycle(hass, entry)

    assert mock.sequence() == []
    assert coordinator.data.dry_run_last_skipped.startswith("Would re-plan the charge target")


async def test_the_log_and_the_reason_sensor_tell_the_story(hass_in_scenario, mock, night):
    hass = hass_in_scenario
    entry, coordinator = await _written_first_target(hass, mock, replan=True)
    coordinator._backend.writer.last_write_time.clear()

    _forecast(hass, 9.0)
    await cycle(hass, entry)
    await cycle(hass, entry)

    notes = [e for e in coordinator._acc.state.register_write_log if e["reason"] == "replan"]
    assert len(notes) == 1
    assert "the forecast for the day after fell by" in notes[0]["value"]
    assert coordinator.data.charge_replan_note.startswith("Re-planned at 02:15: ")
