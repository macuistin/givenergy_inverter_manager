"""The saved totals are still there after a restart, even when entities are learned on the way up.

Home Assistant's Store returns a save that is already queued in place of the file on disk. The
integration learns each wired entity's registry id while it starts, and that used to queue a save
of the still-empty state before the stored totals were read. The empty state was then "loaded" and
written over the totals: the month, the projected bill and every other period read near zero
after the first start of the new version.
"""

from __future__ import annotations

import json

import pytest
from conftest import MIDDAY, SERIAL
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    AccumulationState,
    _serialize,
)


def _stored_totals() -> dict:
    state = AccumulationState()
    state.month.import_kwh = 321.0
    state.month.house_cost = 45.5
    state.week.import_kwh = 40.0
    state.last_full_charge_date = "2026-10-10"
    state.battery_cycles = 573.0
    return _serialize(state)


def _register_the_wiring(hass) -> None:
    """Give the wired entities registry entries, as MQTT entities have, so they can be learned."""
    registry = er.async_get(hass)
    for entity_id in list(hass.states.async_entity_ids()):
        if SERIAL not in entity_id or entity_id.partition(".")[0] not in ("sensor", "number"):
            continue
        state = hass.states.get(entity_id)
        domain, _, name = entity_id.partition(".")
        hass.states.async_remove(entity_id)
        registry.async_get_or_create(domain, "mqtt", f"{SERIAL}_{name}", suggested_object_id=name)
        hass.states.async_set(entity_id, state.state, state.attributes)


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_the_stored_totals_survive_a_start_that_learns_entity_ids(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    hass_storage[_STORAGE_KEY] = {
        "version": 4,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _stored_totals(),
    }
    _register_the_wiring(hass)
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    for _ in range(3):
        await coordinator.async_refresh()

    acc = coordinator._acc
    assert acc.month.import_kwh == pytest.approx(321.0)
    assert acc.month.house_cost == pytest.approx(45.5)
    assert acc.state.last_full_charge_date == "2026-10-10"
    # What it learned is kept as well, so the next start can find a renamed entity.
    assert acc.state.entity_refs

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[_STORAGE_KEY]["data"]
    assert saved["month"]["import_kwh"] == pytest.approx(321.0)
    assert saved["entity_refs"]
    assert json.dumps(saved)  # it is plain data


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_a_second_start_keeps_them_too(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    hass_storage[_STORAGE_KEY] = {
        "version": 4,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _stored_totals(),
    }
    _register_the_wiring(hass)
    config_entry.add_to_hass(hass)
    for _ in range(2):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass_storage[_STORAGE_KEY]["data"]["month"]["import_kwh"] == pytest.approx(321.0)
