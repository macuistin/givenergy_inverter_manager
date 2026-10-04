"""Battery cycle persistence against the real Home Assistant storage layer."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.givenergy_inverter_manager.accumulation import _STORAGE_KEY

V1_CYCLES = 62.6
V1_TRACKING_START_CYCLES = 10.0


@pytest.fixture
def v1_storage(hass_storage):
    """Pre-seed the accumulation store with a version 1 payload (both-directions cycles)."""
    hass_storage[_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": {
            "version": 1,
            "battery_cycles": V1_CYCLES,
            "battery_tracking_start": "2026-01-10",
            "battery_tracking_start_cycles": V1_TRACKING_START_CYCLES,
            "last_full_charge_date": "2026-10-01",
        },
    }
    return hass_storage


async def test_version_1_cycles_are_halved_on_load(hass, v1_storage, loaded_entry):
    """The old both-directions count is converted to discharge only when the entry loads."""
    stats = loaded_entry.runtime_data._battery_stats
    assert stats.total_cycles == pytest.approx(V1_CYCLES / 2)
    assert stats.tracking_start_cycles == pytest.approx(V1_TRACKING_START_CYCLES / 2)


async def test_migrated_store_is_saved_at_the_new_version(hass, v1_storage, loaded_entry):
    assert v1_storage[_STORAGE_KEY]["version"] == 2
    assert v1_storage[_STORAGE_KEY]["data"]["battery_cycles"] == pytest.approx(V1_CYCLES / 2)


async def test_reload_does_not_halve_again(hass, v1_storage, loaded_entry):
    """The conversion runs exactly once, not on every start."""
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED
    stats = loaded_entry.runtime_data._battery_stats
    assert stats.total_cycles == pytest.approx(V1_CYCLES / 2)
    assert stats.tracking_start_cycles == pytest.approx(V1_TRACKING_START_CYCLES / 2)
