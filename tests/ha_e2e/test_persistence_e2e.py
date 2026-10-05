"""Restore the accumulators from storage inside a real Home Assistant instance."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import MIDDAY
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    AccumulationState,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import DOMAIN


def _seed_storage(hass_storage, last_midnight: str) -> None:
    state = AccumulationState()
    state.last_reset_iso = last_midnight
    state.today.solar_kwh = 9.0
    state.week.solar_kwh = 50.0
    state.month.solar_kwh = 200.0
    state.year.solar_kwh = 1500.0
    state.year_start_iso = "2026-01-01T00:00:00+00:00"
    hass_storage[_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _serialize(state),
    }


def _value(hass, entry, key: str) -> float:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return float(hass.states.get(entity_id).state)


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_restart_after_midnight_and_monday_resets_day_and_week(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    """Stored on Sunday 14 June, restarted on Monday 15 June at 13:00 local time."""
    _seed_storage(hass_storage, "2026-06-14T00:00:00+01:00")
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    acc = config_entry.runtime_data._acc
    assert acc.yesterday.solar_kwh == pytest.approx(9.0)
    assert acc.week.solar_kwh == 0.0
    assert acc.state.week_start_iso == "2026-06-15T00:00:00+01:00"
    assert acc.month.solar_kwh == pytest.approx(200.0)
    assert acc.year.solar_kwh == pytest.approx(1500.0)
    assert config_entry.runtime_data._last_reset_time == "2026-06-15T00:00:00+01:00"
    assert _value(hass, config_entry, "solar_yesterday") == pytest.approx(9.0)
    assert _value(hass, config_entry, "solar_this_week") == 0.0


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_restart_across_the_bill_day_resets_the_month(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, freezer
):
    """Bill day is 16. Stored on 14 June, restarted on 17 June."""
    _seed_storage(hass_storage, "2026-06-14T00:00:00+01:00")
    freezer.move_to("2026-06-17 12:00:00+00:00")
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    acc = config_entry.runtime_data._acc
    assert acc.month.solar_kwh == 0.0
    assert acc.state.month_start_iso == "2026-06-16T00:00:00+01:00"
    assert len(acc.monthly_snapshots) == 1
    assert acc.monthly_snapshots[0]["solar_kwh"] == pytest.approx(200.0)
    assert acc.year.solar_kwh == pytest.approx(1500.0)


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_unload_writes_the_accumulators_to_storage(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    """Saving the options reloads the entry. Energy added since the last save must survive."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    config_entry.runtime_data._acc.state.month.solar_kwh = 77.7
    config_entry.runtime_data._battery_stats.total_cycles = 4.25

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    saved = hass_storage[_STORAGE_KEY]["data"]
    assert saved["month"]["solar_kwh"] == pytest.approx(77.7)
    assert saved["battery_cycles"] == pytest.approx(4.25)


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_home_assistant_stop_writes_the_accumulators_to_storage(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    config_entry.runtime_data._acc.state.week.solar_kwh = 31.5

    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()

    assert hass_storage[_STORAGE_KEY]["data"]["week"]["solar_kwh"] == pytest.approx(31.5)


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_tenth_cycle_saves_after_the_delay(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, freezer
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    coordinator._acc.state.year.solar_kwh = 1234.5

    for _ in range(10 - coordinator._update_cycle):
        await coordinator.async_refresh()
    assert hass_storage[_STORAGE_KEY]["data"]["year"]["solar_kwh"] == 0.0

    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass_storage[_STORAGE_KEY]["data"]["year"]["solar_kwh"] == pytest.approx(1234.5)
