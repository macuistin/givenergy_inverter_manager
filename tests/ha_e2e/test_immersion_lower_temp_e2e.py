"""The optional lower hot water thermometer, through real Home Assistant."""

from __future__ import annotations

import pytest
from conftest import IMMERSION_LOWER_TEMP, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_LOWER_TEMP_SENSOR,
    DOMAIN,
)


@pytest.fixture
def scenario():
    return MIDDAY


async def _set_up(hass, *, with_lower: bool = True) -> MockConfigEntry:
    data = full_config_data()
    if not with_lower:
        del data[CONF_IMMERSION_LOWER_TEMP_SENSOR]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _entity_id(hass, entry) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_immersion_lower_water_temperature"
    )


async def test_the_lower_reading_is_a_sensor_on_the_immersion_device(hass_in_scenario):
    hass = hass_in_scenario
    hass.states.async_set(
        IMMERSION_LOWER_TEMP, 29.6, {"unit_of_measurement": "°C", "device_class": "temperature"}
    )
    entry = await _set_up(hass)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    entity_id = _entity_id(hass, entry)
    assert entity_id == "sensor.immersion_lower_water_temperature"
    assert float(hass.states.get(entity_id).state) == 29.6

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_without_the_option_there_is_no_lower_sensor(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass, with_lower=False)

    assert _entity_id(hass, entry) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
