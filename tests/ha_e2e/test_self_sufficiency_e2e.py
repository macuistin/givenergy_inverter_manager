"""Self-sufficiency counts grid energy stored in the battery, inside a real Home Assistant.

The live case: 12.1 kWh imported, 7.5 kWh of it into the battery, 11.3 kWh of house load.
Self-sufficiency read 0 there, because import was larger than the load.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY, PREFIX
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    AccumulationState,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import DOMAIN

_ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy"}
_AC_CHARGE = f"sensor.{PREFIX}_ac_charge_energy_today_kwh"


def _publish_the_live_day(hass, ac_charge_kwh: float | None = 7.5) -> None:
    hass.states.async_set(f"sensor.{PREFIX}_import_energy_today_kwh", 12.1, _ENERGY)
    hass.states.async_set(f"sensor.{PREFIX}_load_energy_today_kwh", 11.3, _ENERGY)
    if ac_charge_kwh is None:
        hass.states.async_remove(_AC_CHARGE)
    else:
        hass.states.async_set(_AC_CHARGE, ac_charge_kwh, _ENERGY)


def _state(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return hass.states.get(entity_id)


async def _refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_overnight_charge_no_longer_reads_as_zero_self_sufficiency(hass, loaded_entry):
    _publish_the_live_day(hass)
    await _refresh(hass, loaded_entry)

    sufficiency = _state(hass, loaded_entry, "self_sufficiency")
    assert float(sufficiency.state) == pytest.approx(59.3, abs=0.05)
    assert sufficiency.attributes["house_load_kwh"] == pytest.approx(11.3)
    assert sufficiency.attributes["from_grid_kwh"] == pytest.approx(4.6)
    assert sufficiency.attributes["grid_to_battery_kwh"] == pytest.approx(7.5)
    assert sufficiency.attributes["from_solar_and_battery_kwh"] == pytest.approx(6.7)
    assert sufficiency.attributes["basis"] == "ac_charge_counter"


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_the_grid_to_battery_sensor_reports_the_counter(hass, loaded_entry):
    _publish_the_live_day(hass)
    await _refresh(hass, loaded_entry)

    sensor = _state(hass, loaded_entry, "grid_to_battery_today")
    assert float(sensor.state) == pytest.approx(7.5)
    assert sensor.attributes["state_class"] == "total"
    assert "last_reset" in sensor.attributes


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_without_the_counter_the_old_figure_is_kept_and_says_so(hass, loaded_entry):
    _publish_the_live_day(hass, ac_charge_kwh=None)
    await _refresh(hass, loaded_entry)

    sufficiency = _state(hass, loaded_entry, "self_sufficiency")
    assert float(sufficiency.state) == 0.0
    assert sufficiency.attributes["basis"] == "import_only"
    assert sufficiency.attributes["from_grid_kwh"] == pytest.approx(12.1)
    assert sufficiency.attributes["grid_to_battery_kwh"] == 0.0
    assert _state(hass, loaded_entry, "grid_to_battery_today").state == STATE_UNAVAILABLE


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_week_and_month_count_the_stored_charge_too(hass, loaded_entry):
    _publish_the_live_day(hass)
    await _refresh(hass, loaded_entry)

    for key in ("self_sufficiency_this_week", "self_sufficiency_this_month"):
        attributes = _state(hass, loaded_entry, key).attributes
        assert attributes["grid_to_battery_kwh"] == pytest.approx(7.5), key
        assert attributes["basis"] == "ac_charge_counter", key


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_the_counter_reset_at_midnight_keeps_the_week_and_clears_today(
    hass, loaded_entry, freezer
):
    _publish_the_live_day(hass)
    await _refresh(hass, loaded_entry)

    # Local midnight in Europe/Dublin (UTC+1 in June), then GivTCP resets its counters.
    freezer.move_to("2026-06-15 23:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.states.async_set(f"sensor.{PREFIX}_import_energy_today_kwh", 0.0, _ENERGY)
    hass.states.async_set(f"sensor.{PREFIX}_load_energy_today_kwh", 0.1, _ENERGY)
    hass.states.async_set(_AC_CHARGE, 0.0, _ENERGY)
    await _refresh(hass, loaded_entry)

    assert float(_state(hass, loaded_entry, "grid_to_battery_today").state) == 0.0
    today = _state(hass, loaded_entry, "self_sufficiency")
    assert today.attributes["grid_to_battery_kwh"] == 0.0
    yesterday = _state(hass, loaded_entry, "self_sufficiency_yesterday")
    assert yesterday.attributes["grid_to_battery_kwh"] == pytest.approx(7.5)
    week = _state(hass, loaded_entry, "self_sufficiency_this_week")
    assert week.attributes["grid_to_battery_kwh"] == pytest.approx(7.5)


def _version_3_payload() -> dict:
    """What storage version 3 held: no grid-to-battery figure anywhere."""
    state = AccumulationState()
    state.last_reset_iso = "2026-06-15T00:00:00+01:00"
    state.week_start_iso = "2026-06-15T00:00:00+01:00"
    state.month_start_iso = "2026-05-16T00:00:00+01:00"
    state.year_start_iso = "2026-01-01T00:00:00+00:00"
    payload = _serialize(state)
    payload["version"] = 3
    del payload["ac_charge_counter_kwh"]
    for period in ("today", "week", "month", "year", "yesterday"):
        del payload[period]["grid_to_battery_kwh"]
    payload["week"].update(house_kwh=40.0, import_kwh=50.0)
    return payload


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_version_3_storage_loads_and_then_accumulates_the_charge(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    hass_storage[_STORAGE_KEY] = {
        "version": 3,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _version_3_payload(),
    }
    _publish_the_live_day(hass)
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    acc = config_entry.runtime_data._acc
    assert acc.week.import_kwh == pytest.approx(50.0)
    assert acc.week.grid_to_battery_kwh == pytest.approx(7.5)
    assert acc.today.grid_to_battery_kwh == pytest.approx(7.5)
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[_STORAGE_KEY]["data"]
    assert saved["version"] == 4
    assert saved["week"]["grid_to_battery_kwh"] == pytest.approx(7.5)
    assert saved["ac_charge_counter_kwh"] == pytest.approx(7.5)
