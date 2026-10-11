"""The volatile attributes stay in the live state and stay out of the real recorder.

Home Assistant writes a new row of attributes whenever one attribute changes, even when the
state did not. The attributes in GivEnergyManagerSensor._unrecorded_attributes are not written.
This test reads the states back from a real recorder (the plugin's recorder_mock, an in-memory
SQLite database) and compares them with the live state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.givenergy_inverter_manager.const import DOMAIN

# What the plan says is not recorded, per sensor. The live state must still carry it. The night
# survival sensor is off by default, so tests/test_unrecorded_attributes.py covers its names.
NOT_RECORDED = {
    "water_heating_cheapest_source": {
        "alt_cost_per_kwh",
        "electricity_cost_per_kwh",
        "cheapest_electricity_cost_per_kwh",
        "alt_saving_per_kwh",
        "best_hours_for_alt",
        "horizon_ends",
        "alt_keep_warm",
    },
    "self_sufficiency": {
        "house_load_kwh",
        "from_grid_kwh",
        "grid_to_battery_kwh",
        "from_solar_and_battery_kwh",
    },
    "register_write_count": {"recent_writes"},
}
# What explains the state and is recorded.
RECORDED = {
    "water_heating_cheapest_source": {"suggestion", "alt_label", "horizon"},
    "self_sufficiency": {"basis"},
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Start the recorder before hass, which the plugin's recorder fixtures require."""
    return None


@pytest.fixture
def scenario():
    return MIDDAY


async def _recorded(hass, entity_id: str) -> dict:
    """The attributes the recorder holds for the entity's latest state."""
    await async_wait_recording_done(hass)
    start = dt_util.utcnow() - timedelta(days=1)
    history = await get_instance(hass).async_add_executor_job(
        lambda: get_significant_states(
            hass, start, entity_ids=[entity_id], significant_changes_only=False
        )
    )
    return dict(history[entity_id][-1].attributes)


@pytest.fixture
async def entry(hass_in_scenario, service_calls):
    hass = hass_in_scenario
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=full_config_data(),
        options={"alt_heat_enabled": True, "alt_heat_cost": 0.05},
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    return entry


def _entity_id(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


@pytest.mark.parametrize("key", sorted(NOT_RECORDED))
async def test_the_live_state_has_every_attribute(hass_in_scenario, entry, key):
    hass = hass_in_scenario
    live = hass.states.get(_entity_id(hass, entry, key)).attributes
    published = NOT_RECORDED[key] - {"alt_keep_warm", "recent_writes"}
    assert published <= set(live), sorted(published - set(live))


@pytest.mark.parametrize("key", sorted(NOT_RECORDED))
async def test_the_recorder_holds_none_of_the_unrecorded_ones(hass_in_scenario, entry, key):
    hass = hass_in_scenario
    recorded = await _recorded(hass, _entity_id(hass, entry, key))
    assert NOT_RECORDED[key].isdisjoint(recorded), sorted(NOT_RECORDED[key] & set(recorded))


@pytest.mark.parametrize("key", sorted(RECORDED))
async def test_the_recorder_still_holds_what_explains_the_state(hass_in_scenario, entry, key):
    hass = hass_in_scenario
    recorded = await _recorded(hass, _entity_id(hass, entry, key))
    assert RECORDED[key] <= set(recorded), sorted(RECORDED[key] - set(recorded))


async def test_the_keep_warm_sentence_is_live_and_not_recorded(hass_in_scenario, entry):
    """The scenario's water is cooling, so the keep-warm run is published."""
    hass = hass_in_scenario
    entity_id = _entity_id(hass, entry, "water_heating_cheapest_source")
    assert "alt_keep_warm" in hass.states.get(entity_id).attributes
    assert "alt_keep_warm" not in await _recorded(hass, entity_id)


async def test_a_changed_cost_writes_no_new_attribute_row_for_the_unrecorded_ones(
    hass_in_scenario, entry
):
    """Only the recorded attributes decide whether a new row of attributes is stored."""
    hass = hass_in_scenario
    entity_id = _entity_id(hass, entry, "water_heating_cheapest_source")
    before = await _recorded(hass, entity_id)

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "alt_heat_cost": 0.06}
    )
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    live = hass.states.get(entity_id).attributes
    assert live["alt_cost_per_kwh"] != 0.05 / (10.35 * 0.85)
    after = await _recorded(hass, entity_id)
    assert after == before
