"""Battery cycle persistence against the real Home Assistant storage layer."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.accumulation import _STORAGE_KEY
from custom_components.givenergy_inverter_manager.const import DOMAIN

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


PACK_1 = "sensor.givtcp_bt2349g123_battery_cycles"
PACK_2 = "sensor.givtcp_bt2349g456_battery_cycles"


@pytest.fixture
def bms_packs(hass_in_scenario):
    """Two battery packs publishing their own BMS cycle counters."""
    hass_in_scenario.states.async_set(PACK_1, 38)
    hass_in_scenario.states.async_set(PACK_2, 41)
    return hass_in_scenario


def _sensor_state(hass, entry, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return hass.states.get(entity_id).state


async def test_total_cycles_sensor_uses_the_highest_bms_counter(hass, bms_packs, loaded_entry):
    """Discovery by naming picks up both packs and the sensor shows the highest, not the sum."""
    assert float(_sensor_state(hass, loaded_entry, "battery_cycles")) == pytest.approx(41.0)


async def test_remaining_life_uses_the_bms_counter(hass, bms_packs, loaded_entry):
    expected = round((1 - 41 / 6000) * 100, 1)
    assert float(_sensor_state(hass, loaded_entry, "battery_remaining_life")) == pytest.approx(
        expected
    )


async def test_soc_estimate_is_used_without_a_bms_counter(hass, loaded_entry):
    """No battery_cycles entity exists, so the SoC estimate (starting at zero) applies."""
    assert float(_sensor_state(hass, loaded_entry, "battery_cycles")) == pytest.approx(0.0)
