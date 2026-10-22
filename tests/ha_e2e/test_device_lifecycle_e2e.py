"""The EV charger and Immersion devices follow their hardware: added, placed and removed."""

from __future__ import annotations

import pytest
from conftest import MIDDAY, ZAPPI_STATES, discover_the_charger, full_config_data
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from custom_components.givenergy_inverter_manager import async_remove_config_entry_device
from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)


@pytest.fixture
def scenario():
    return MIDDAY


def _devices(hass, entry) -> dict[str, dr.DeviceEntry]:
    """The entry's devices by the name of their identifier suffix: main, ev_charger, immersion."""
    found = {}
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        (_, identifier) = next(iter(device.identifiers))
        found[identifier.removeprefix(entry.entry_id).lstrip("_") or "main"] = device
    return found


async def test_the_immersion_device_goes_when_its_hardware_is_cleared(hass, loaded_entry):
    assert "immersion" in _devices(hass, loaded_entry)
    data = full_config_data()
    data.pop(CONF_IMMERSION_SWITCH)
    data.pop(CONF_IMMERSION_TEMP_SENSOR)

    hass.config_entries.async_update_entry(loaded_entry, data=data)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert set(_devices(hass, loaded_entry)) == {"main"}


async def test_a_device_in_use_cannot_be_deleted_and_one_without_hardware_can(hass, loaded_entry):
    devices = _devices(hass, loaded_entry)

    assert await async_remove_config_entry_device(hass, loaded_entry, devices["main"]) is False
    assert await async_remove_config_entry_device(hass, loaded_entry, devices["immersion"]) is False

    data = full_config_data()
    data.pop(CONF_IMMERSION_SWITCH)
    data.pop(CONF_IMMERSION_TEMP_SENSOR)
    hass.config_entries.async_update_entry(loaded_entry, data=data)
    # The update listener reloads the entry. Wait for it, so runtime_data is back.
    await hass.async_block_till_done()

    assert await async_remove_config_entry_device(hass, loaded_entry, devices["immersion"]) is True
    assert await async_remove_config_entry_device(hass, loaded_entry, devices["main"]) is False


async def test_a_charger_found_later_gets_a_device_in_the_area_of_the_main_device(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert "ev_charger" not in _devices(hass, config_entry)
    area = ar.async_get(hass).async_create("Utility room")
    main = _devices(hass, config_entry)["main"]
    dr.async_get(hass).async_update_device(main.id, area_id=area.id)

    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    await discover_the_charger(hass, config_entry)

    charger = _devices(hass, config_entry)["ev_charger"]
    assert charger.via_device_id == main.id
    assert charger.area_id == area.id
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_an_area_the_user_clears_is_not_put_back(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    area = ar.async_get(hass).async_create("Utility room")
    registry = dr.async_get(hass)
    registry.async_update_device(_devices(hass, config_entry)["main"].id, area_id=area.id)
    immersion = _devices(hass, config_entry)["immersion"]
    registry.async_update_device(immersion.id, area_id=None)

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _devices(hass, config_entry)["immersion"].area_id is None
    await hass.config_entries.async_unload(config_entry.entry_id)
