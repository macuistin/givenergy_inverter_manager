"""The half-hourly energy history in a real Home Assistant: recorded, saved and read back."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay, SlotEnergy
from custom_components.givenergy_inverter_manager.slot_store import _STORAGE_KEY


async def _cycle(hass, freezer, entry, count: int = 3) -> None:
    """Run cycles 30 seconds apart, so each has an interval to record."""
    for _ in range(count):
        freezer.tick(30)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _today(hass):
    return dt_util.now().date()


async def test_each_cycle_is_booked_into_todays_slots(hass, freezer, loaded_entry):
    await _cycle(hass, freezer, loaded_entry)
    day = loaded_entry.runtime_data._slots.history.get(_today(hass))
    assert day is not None
    assert day.coverage > 0
    # Setup's own refresh gives the first cycle its start, so three cycles are three intervals.
    assert sum(day.seconds) == pytest.approx(90, abs=1)


async def test_the_battery_charge_is_noted_in_the_slot(hass, freezer, loaded_entry):
    await _cycle(hass, freezer, loaded_entry)
    day = loaded_entry.runtime_data._slots.history.get(_today(hass))
    assert any(value is not None for value in day.soc_pct)


async def test_the_history_is_saved_and_has_the_stored_shape(
    hass, freezer, loaded_entry, hass_storage
):
    await _cycle(hass, freezer, loaded_entry)
    await loaded_entry.runtime_data._slots.async_save()
    saved = hass_storage[_STORAGE_KEY]["data"]
    assert saved["version"] == 1
    day = saved["days"][-1]
    assert day["date"] == _today(hass).isoformat()
    assert set(day) == {
        "version", "date", "start", "slots", "flows_wh", "loads_wh", "soc_pct", "seconds",
        "counters_wh",
    }  # fmt: skip
    assert set(day["loads_wh"]) >= {"house", "ev", "immersion"}


async def test_a_saved_history_is_read_back_at_start(hass, hass_in_scenario, hass_storage, config_entry):
    yesterday = _today(hass) - timedelta(days=1)
    day = SlotDay(yesterday, dt_util.get_default_time_zone())
    start = day.start + timedelta(hours=3)
    day.add(SlotEnergy(flows={"import": 0.4}), start, start + timedelta(minutes=10))
    hass_storage[_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": {"version": 1, "days": [day.to_storage()]},
    }
    config_entry.add_to_hass(hass_in_scenario)
    assert await hass_in_scenario.config_entries.async_setup(config_entry.entry_id)
    await hass_in_scenario.async_block_till_done()

    restored = config_entry.runtime_data._slots.history.get(yesterday)
    assert restored is not None
    assert restored.total("import") == pytest.approx(0.4, abs=0.001)
