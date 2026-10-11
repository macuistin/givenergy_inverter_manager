"""Auto Immersion Divert keeps its state across a restart.

Without it, turning auto divert off and restarting Home Assistant would silently hand the
immersion heater back to the integration. The Enable Charge Target Override switch is
covered in test_charge_override_e2e.py.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import mock_restore_cache

SWITCH = "switch.givenergy_inverter_manager_auto_immersion_divert"


@pytest.fixture
def scenario():
    return MIDDAY


async def test_restored_off_stays_off_and_blocks_automatic_divert(hass, loaded_entry_restored_off):
    coordinator = loaded_entry_restored_off.runtime_data

    assert hass.states.get(SWITCH).state == "off"
    assert coordinator.override_immersion is False


async def test_restored_on_stays_on_and_leaves_divert_automatic(hass, loaded_entry_restored_on):
    coordinator = loaded_entry_restored_on.runtime_data

    assert hass.states.get(SWITCH).state == "on"
    assert coordinator.override_immersion is None


async def test_with_nothing_to_restore_it_is_on(hass, loaded_entry):
    assert hass.states.get(SWITCH).state == "on"
    assert loaded_entry.runtime_data.override_immersion is None


async def _load_with_restored(hass, config_entry, restored: str):
    mock_restore_cache(hass, [State(SWITCH, restored)])
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def loaded_entry_restored_off(hass, hass_in_scenario, service_calls, config_entry):
    async for entry in _load_with_restored(hass, config_entry, "off"):
        yield entry


@pytest.fixture
async def loaded_entry_restored_on(hass, hass_in_scenario, service_calls, config_entry):
    async for entry in _load_with_restored(hass, config_entry, "on"):
        yield entry
