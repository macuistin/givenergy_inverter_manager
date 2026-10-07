"""Installs with no immersion switch or EV charger, and ones that gain a device later."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import IMMERSION_SWITCH, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.reporting import (
    build_today_summary_html,
    build_today_summary_state,
    build_week_summary_html,
)

NO_SWITCH_REASON = "No immersion switch configured"

# Battery full, solar well above the house load, all the surplus exported.
FULL_AND_EXPORTING = replace(
    MIDDAY,
    name="full_and_exporting",
    battery_soc=100.0,
    battery_w=0.0,
    grid_w=3000.0,
    solar_w=5000.0,
)

ZAPPI = {
    "sensor.myenergi_zappi_plug_status": "EV Connected",
    "sensor.myenergi_zappi_status": "Paused",
    "sensor.myenergi_zappi_internal_load_ct1": "0",
    "sensor.myenergi_zappi_charge_added_session": "0.0",
    "sensor.myenergi_zappi_serial_number": "21637627",
    "select.myenergi_zappi_charge_mode": "Eco+",
}


@pytest.fixture
def scenario():
    return FULL_AND_EXPORTING


def _entry_without_immersion() -> MockConfigEntry:
    data = full_config_data()
    for key in (
        CONF_IMMERSION_SWITCH,
        CONF_IMMERSION_TEMP_SENSOR,
        CONF_IMMERSION_WATTAGE,
        CONF_IMMERSION_TARGET_TEMP,
        CONF_IMMERSION_MIN_TEMP,
    ):
        data.pop(key)
    return MockConfigEntry(
        domain=DOMAIN, title="GivEnergy Inverter Manager", data=data, unique_id=SERIAL, version=1
    )


async def _set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _run_cycles(hass, entry, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(timedelta(seconds=30))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _sensor_state(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return hass.states.get(entity_id).state


async def test_no_devices_means_no_immersion_claims(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    entry = _entry_without_immersion()
    await _set_up(hass, entry)
    await _run_cycles(hass, entry, freezer, 4)

    data = entry.runtime_data.data
    assert data.should_divert_immersion is False
    assert _sensor_state(hass, entry, "immersion_divert_reason") == NO_SWITCH_REASON
    assert data.today.missed_solar_kwh == 0.0
    assert _sensor_state(hass, entry, "ev_solar_surplus_available") == "unavailable"
    for text in (
        build_today_summary_html(data),
        build_today_summary_state(data),
        build_week_summary_html(data),
    ):
        assert "Immersion" not in text
        assert "Saved" not in text
    assert not service_calls["switch.turn_on"]


async def test_an_immersion_switch_added_later_takes_effect_without_a_restart(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    hass.states.async_set(IMMERSION_SWITCH, "off")
    entry = _entry_without_immersion()
    await _set_up(hass, entry)
    await _run_cycles(hass, entry, freezer, 2)
    assert _sensor_state(hass, entry, "immersion_divert_reason") == NO_SWITCH_REASON

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_IMMERSION_SWITCH: IMMERSION_SWITCH}
    )
    await hass.async_block_till_done()
    await _run_cycles(hass, entry, freezer, 4)

    assert entry.state is ConfigEntryState.LOADED
    data = entry.runtime_data.data
    assert _sensor_state(hass, entry, "immersion_divert_reason") != NO_SWITCH_REASON
    assert data.today.missed_solar_kwh > 0.0
    assert "Immersion" in build_today_summary_html(data)


async def test_an_ev_charger_added_later_is_found_and_its_sensor_comes_alive(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = _entry_without_immersion()
    await _set_up(hass, entry)
    await _run_cycles(hass, entry, freezer, 2)
    assert _sensor_state(hass, entry, "ev_solar_surplus_available") == "unavailable"
    assert entry.runtime_data.data.today.missed_solar_kwh == 0.0

    for entity_id, value in ZAPPI.items():
        hass.states.async_set(entity_id, value)
    await _run_cycles(hass, entry, freezer, 12)

    assert entry.runtime_data._ev_charger is not None
    assert _sensor_state(hass, entry, "ev_solar_surplus_available") in {
        "Available",
        "Not available",
    }
    assert entry.runtime_data.data.today.missed_solar_kwh > 0.0
