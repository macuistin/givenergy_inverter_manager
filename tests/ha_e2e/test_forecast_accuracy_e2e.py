"""Forecast accuracy is measured against the raw forecast for the day, inside real Home Assistant."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    AccumulationState,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import DOMAIN

# MIDDAY publishes 12.4 kWh for the GivTCP daily solar counter, which the coordinator applies
# to today's total after every cycle.
SOLAR_TODAY_KWH = 12.4


@pytest.fixture
def scenario():
    return MIDDAY


async def _refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _seed_v2_storage(hass_storage, ratio_history: list[dict]) -> None:
    """Storage as written by 0.9.0, whose accuracy history came from the blended forecast."""
    state = AccumulationState()
    state.last_reset_iso = "2026-06-15T00:00:00+01:00"
    state.yesterday_forecast_accuracy_pct = 19.0
    state.forecast_accuracy_history = [19.0, 22.0]
    state.forecast_ratio_history = ratio_history
    data = _serialize(state)
    data["version"] = 2
    hass_storage[_STORAGE_KEY] = {
        "version": 2,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": data,
    }


async def test_midnight_measures_accuracy_against_the_raw_forecast(
    hass, loaded_entry, freezer
):
    """A 01:59 charge decision forecast of 35 kWh must not become the denominator."""
    acc = loaded_entry.runtime_data._acc
    acc.state.today_raw_forecast_kwh = 14.0
    acc.state.today_forecast_kwh = 35.0

    freezer.move_to("2026-06-15 23:00:00+00:00")  # local midnight in Europe/Dublin
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await _refresh(hass, loaded_entry)

    assert acc.yesterday.solar_kwh == pytest.approx(SOLAR_TODAY_KWH)
    data = loaded_entry.runtime_data.data
    assert data.yesterday_forecast_accuracy_pct == pytest.approx(88.6)
    assert data.forecast_accuracy_7day_avg_pct == pytest.approx(88.6)


async def test_midnight_without_a_remembered_forecast_records_no_accuracy(
    hass, loaded_entry, freezer
):
    acc = loaded_entry.runtime_data._acc
    acc.state.today_raw_forecast_kwh = 0.0
    acc.state.today_forecast_kwh = 35.0

    freezer.move_to("2026-06-15 23:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await _refresh(hass, loaded_entry)

    assert loaded_entry.runtime_data.data.yesterday_forecast_accuracy_pct == 0.0
    assert acc.state.forecast_accuracy_history == []


async def test_upgrade_rebuilds_the_accuracy_from_the_stored_raw_forecasts(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    _seed_v2_storage(
        hass_storage,
        [
            {"forecast": 14.0, "actual": 12.4, "clipped": False},
            {"forecast": 7.54, "actual": 6.64, "clipped": False},
        ],
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _refresh(hass, config_entry)

    assert config_entry.runtime_data._acc.state.forecast_accuracy_history == [88.6, 88.1]
    data = config_entry.runtime_data.data
    assert data.yesterday_forecast_accuracy_pct == pytest.approx(88.1)
    assert data.forecast_accuracy_7day_avg_pct == pytest.approx(88.35, abs=0.06)


async def test_upgrade_with_no_stored_raw_forecasts_starts_the_accuracy_fresh(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    _seed_v2_storage(hass_storage, [])
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _refresh(hass, config_entry)

    assert config_entry.runtime_data._acc.state.forecast_accuracy_history == []
    assert config_entry.runtime_data.data.yesterday_forecast_accuracy_pct == 0.0


def _state(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id).state


async def test_tracking_compares_solar_with_the_provider_forecast_not_the_plan(
    hass, loaded_entry
):
    """The plan held 35 kWh, the provider 14. 12.4 kWh generated is 88.6% of the provider's day."""
    acc = loaded_entry.runtime_data._acc
    acc.state.today_raw_forecast_kwh = 14.0
    acc.state.today_forecast_kwh = 35.0

    await _refresh(hass, loaded_entry)

    assert float(_state(hass, loaded_entry, "solar_forecast_raw_today")) == pytest.approx(14.0)
    assert float(_state(hass, loaded_entry, "solar_forecast_kwh_today")) == pytest.approx(35.0)
    assert float(_state(hass, loaded_entry, "solar_actual_vs_forecast_pct")) == pytest.approx(88.6)


async def test_tracking_is_unknown_without_a_provider_forecast_for_today(hass, loaded_entry):
    """A forecast first seen after midnight belongs to tomorrow, so today has none to track."""
    acc = loaded_entry.runtime_data._acc
    acc.state.today_raw_forecast_kwh = 0.0
    acc.state.today_forecast_kwh = 35.0

    await _refresh(hass, loaded_entry)

    assert _state(hass, loaded_entry, "solar_forecast_raw_today") == "unknown"
    assert _state(hass, loaded_entry, "solar_actual_vs_forecast_pct") == "unknown"
    assert float(_state(hass, loaded_entry, "solar_forecast_kwh_today")) == pytest.approx(35.0)
