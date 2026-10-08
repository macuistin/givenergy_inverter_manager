"""A reload in the middle of the day keeps the energy accumulated so far."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import MIDDAY, PREFIX
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

_COUNTERS = (
    "pv_energy_today_kwh",
    "import_energy_today_kwh",
    "ac_charge_energy_today_kwh",
    "export_energy_today_kwh",
    "battery_charge_energy_today_kwh",
    "battery_discharge_energy_today_kwh",
    "load_energy_today_kwh",
)


def _value(hass, entry, key: str) -> float:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return float(hass.states.get(entity_id).state)


def _charged_kwh(entry) -> float:
    """Today's battery charge, read from the snapshot because the sensor is off by default."""
    return entry.runtime_data.data.today.battery_charge_kwh


async def _run_for(hass, entry, freezer, minutes: int) -> None:
    for _ in range(minutes * 2):
        freezer.tick(timedelta(seconds=30))
        await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_reload_without_counters_keeps_the_integrated_day(
    hass, loaded_entry, freezer
):
    for suffix in _COUNTERS:
        hass.states.async_remove(f"sensor.{PREFIX}_{suffix}")
    await _run_for(hass, loaded_entry, freezer, 20)
    before = _charged_kwh(loaded_entry)
    house_before = _value(hass, loaded_entry, "house_kwh_today")
    assert before > 0.3

    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert _charged_kwh(loaded_entry) >= before
    assert _value(hass, loaded_entry, "house_kwh_today") >= house_before


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_reload_with_counters_shows_the_counters_at_once(hass, loaded_entry, freezer):
    await _run_for(hass, loaded_entry, freezer, 5)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert _charged_kwh(loaded_entry) == pytest.approx(5.2)
    assert _value(hass, loaded_entry, "battery_discharge_kwh_today") == pytest.approx(2.2)
