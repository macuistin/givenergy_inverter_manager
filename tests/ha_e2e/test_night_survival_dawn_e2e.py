"""Night survival at dawn, through the real Home Assistant runtime.

The solar reading wanders across the noise floor in the first minutes after sunrise. The
coordinator carries the settled solar state between cycles, so the status does not flip with it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import CHEAP_NIGHT, PREFIX, SOLAR, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN, SOLAR_NOISE_FLOOR_W
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.sensor_values import night_survival_confidence

# 08:00 local on an October morning (UTC+1 until the clocks change). The battery lasts the 8-hour
# pre-solar window but not the 24 hours to tomorrow's sunrise.
OCTOBER_DAWN = replace(
    CHEAP_NIGHT,
    name="october_dawn",
    frozen_utc="2026-10-09 07:00:00+00:00",
    battery_soc=87.0,
)
LOAD_TODAY_KWH = 4.0  # 12 kWh a day at 08:00
CYCLE = timedelta(seconds=30)
CYCLES = 20
BELOW_W = SOLAR_NOISE_FLOOR_W - 1.0
ABOVE_W = SOLAR_NOISE_FLOOR_W + 2.0


def _sensor_state(hass, entry, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return hass.states.get(entity_id).state


async def _set_up(hass):
    hass.states.async_set(
        f"sensor.{PREFIX}_load_energy_today_kwh",
        LOAD_TODAY_KWH,
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=full_config_data(),
        unique_id="ab1234g567",
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _flicker(hass, entry, freezer, *, remember: bool) -> list[tuple[str, str]]:
    """Alternate 9 W and 12 W for CYCLES cycles, returning the status and level after each."""
    shown = []
    for i in range(CYCLES):
        if not remember:
            entry.runtime_data._held_solar = HeldSolarDay()
        hass.states.async_set(
            SOLAR, BELOW_W if i % 2 == 0 else ABOVE_W, {"unit_of_measurement": "W"}
        )
        freezer.tick(CYCLE)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        shown.append(
            (
                "shortfall" if "shortfall" in _sensor_state(hass, entry, "night_survival_reason") else "last",
                night_survival_confidence(entry.runtime_data.data),
            )
        )
    return shown


@pytest.mark.parametrize("scenario", [OCTOBER_DAWN], ids=lambda s: s.name)
async def test_without_the_held_solar_state_the_status_flips_with_the_reading(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    shown = await _flicker(hass, entry, freezer, remember=False)
    assert len(set(shown)) > 1, shown
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("scenario", [OCTOBER_DAWN], ids=lambda s: s.name)
async def test_the_coordinator_keeps_the_status_steady_through_the_flicker(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    shown = await _flicker(hass, entry, freezer, remember=True)
    assert len(set(shown)) == 1, shown
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
