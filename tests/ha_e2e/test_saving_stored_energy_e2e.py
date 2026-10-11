"""The saving sensors show the value of the energy the battery gained since the day began.

The first cycle notes the SoC the day began at. When the SoC rises, both saving sensors carry the
change in kWh and its value as attributes, and the saving counts it.
"""

from __future__ import annotations

import pytest
from conftest import CHEAP_NIGHT, SERIAL, SOC, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_CAPACITY, DOMAIN

CAPACITY_KWH = 9.5  # from full_config_data


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


async def _load(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), options={}, unique_id=SERIAL, version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _sensor(hass, entry, key):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return hass.states.get(entity_id)


async def test_a_rise_in_soc_is_reported_on_both_saving_sensors(hass, hass_in_scenario):
    entry = await _load(hass)
    assert entry.data[CONF_BATTERY_CAPACITY] == CAPACITY_KWH
    first = _sensor(hass, entry, "saving_vs_grid_today").attributes
    assert first["stored_energy_change_kwh"] == 0.0
    assert first["stored_energy_value"] == 0.0

    hass.states.async_set(SOC, "51", {"unit_of_measurement": "%", "device_class": "battery"})
    await entry.runtime_data.async_refresh()

    for key in ("saving_vs_grid_today", "net_saving_today"):
        attributes = _sensor(hass, entry, key).attributes
        assert attributes["stored_energy_change_kwh"] == pytest.approx(0.20 * CAPACITY_KWH, abs=1e-3)
        assert attributes["stored_energy_value"] > 0
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_saving_counts_the_stored_energy(hass, hass_in_scenario):
    entry = await _load(hass)
    before = float(_sensor(hass, entry, "saving_vs_grid_today").state)

    hass.states.async_set(SOC, "51", {"unit_of_measurement": "%", "device_class": "battery"})
    await entry.runtime_data.async_refresh()

    saving = _sensor(hass, entry, "saving_vs_grid_today")
    value = saving.attributes["stored_energy_value"]
    assert float(saving.state) == pytest.approx(before + value, abs=0.01)
    await hass.config_entries.async_unload(entry.entry_id)
