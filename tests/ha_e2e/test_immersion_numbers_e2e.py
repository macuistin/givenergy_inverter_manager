"""Moving an immersion temperature number must not reload the integration."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.components.number import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import (
    CONF_EXPORT_RATE,
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_TARGET_TEMP,
    DOMAIN,
)


@pytest.fixture
def scenario():
    return MIDDAY


def _number(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return hass.data[DATA_COMPONENT].get_entity(entity_id)


async def test_moving_the_target_slider_keeps_the_running_coordinator(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    target = _number(hass, loaded_entry, "immersion_target_temp")

    await target.async_set_native_value(62)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data is coordinator
    assert coordinator.immersion_target_temp == 62
    assert loaded_entry.data[CONF_IMMERSION_TARGET_TEMP] == 62


async def test_every_immersion_slider_skips_the_reload(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    for key, value, attr in (
        ("immersion_min_temp", 48, "immersion_min_temp"),
        ("immersion_hysteresis", 8, "immersion_hysteresis_c"),
        ("immersion_target_temp", 60, "immersion_target_temp"),
    ):
        await _number(hass, loaded_entry, key).async_set_native_value(value)
        await hass.async_block_till_done()
        assert loaded_entry.runtime_data is coordinator, key
        assert getattr(coordinator, attr) == value, key
    assert loaded_entry.data[CONF_IMMERSION_MIN_TEMP] == 48
    assert loaded_entry.data[CONF_IMMERSION_HYSTERESIS] == 8


async def test_a_change_to_other_data_still_reloads(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    hass.config_entries.async_update_entry(
        loaded_entry, data={**loaded_entry.data, CONF_EXPORT_RATE: 0.25}
    )
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data is not coordinator
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.25)


async def test_a_mixed_change_still_reloads(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    hass.config_entries.async_update_entry(
        loaded_entry,
        data={**loaded_entry.data, CONF_IMMERSION_TARGET_TEMP: 65, CONF_EXPORT_RATE: 0.26},
    )
    await hass.async_block_till_done()

    assert loaded_entry.runtime_data is not coordinator
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.26)


async def test_an_outside_change_to_a_slider_key_updates_the_coordinator(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    hass.config_entries.async_update_entry(
        loaded_entry, data={**loaded_entry.data, CONF_IMMERSION_HYSTERESIS: 3}
    )
    await hass.async_block_till_done()

    assert loaded_entry.runtime_data is coordinator
    assert coordinator.immersion_hysteresis_c == 3


async def test_a_target_below_the_minimum_is_stored_clamped(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    await _number(hass, loaded_entry, "immersion_target_temp").async_set_native_value(45)
    await hass.async_block_till_done()

    assert coordinator.immersion_target_temp == 51
    assert loaded_entry.data[CONF_IMMERSION_TARGET_TEMP] == 51
