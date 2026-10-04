"""The GivTCP register write count survives a restart of the integration."""

from __future__ import annotations

import pytest
from conftest import TARGET_SOC
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.givenergy_inverter_manager.accumulation import _STORAGE_KEY

RESTORED = 250_000


@pytest.fixture
def stored_count(hass_storage):
    hass_storage[_STORAGE_KEY] = {
        "version": 2,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": {"version": 2, "register_write_count": RESTORED},
    }
    return hass_storage


async def test_count_is_restored_when_the_entry_loads(hass, stored_count, loaded_entry):
    assert loaded_entry.runtime_data._register_write_count >= RESTORED


async def test_count_survives_a_reload(hass, stored_count, loaded_entry):
    async_mock_service(hass, "number", "set_value")
    coordinator = loaded_entry.runtime_data
    coordinator._last_write_time.clear()
    hass.states.async_set(TARGET_SOC, 5)

    assert await coordinator._givtcp_set_number(TARGET_SOC, 55, "target")
    count = coordinator._register_write_count
    assert count > RESTORED
    await coordinator._acc.async_save()
    assert stored_count[_STORAGE_KEY]["data"]["register_write_count"] == count

    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data._register_write_count >= count
