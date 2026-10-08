"""Night survival with a car charging overnight, through the real Home Assistant runtime.

An EV drawing 7.2 kW for hours is not house load the battery has to cover. The estimate and the
status stay where the house alone puts them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import CHEAP_NIGHT, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN

# 01:10 local in June. The house draws 800 W and the car 7.2 kW, all imported on the cheap rate.
EV_JUNE_NIGHT = replace(
    CHEAP_NIGHT,
    name="ev_june_night",
    frozen_utc="2026-06-15 00:10:00+00:00",
    battery_soc=80.0,
    grid_w=-8000.0,
    load_w=8000.0,
)

ZAPPI_CHARGING = {
    "sensor.myenergi_zappi_plug_status": "EV Connected",
    "sensor.myenergi_zappi_status": "Boosting",
    "sensor.myenergi_zappi_internal_load_ct1": "7200",
    "sensor.myenergi_zappi_charge_added_session": "3.2",
    "sensor.myenergi_zappi_serial_number": "21637627",
    "select.myenergi_zappi_charge_mode": "Fast",
}

# Three and a half hours of charging, in steps under the hour the accumulator accepts.
STEP = timedelta(minutes=50)
STEPS = 4


def _sensor_state(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return hass.states.get(entity_id)


@pytest.mark.parametrize("scenario", [EV_JUNE_NIGHT], ids=lambda s: s.name)
async def test_overnight_ev_charge_does_not_empty_the_night_survival_estimate(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    for entity_id, value in ZAPPI_CHARGING.items():
        hass.states.async_set(entity_id, value)
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

    for _ in range(STEPS):
        freezer.tick(STEP)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    data = entry.runtime_data.data
    assert data.today.zappi_kwh > 20.0, "the car's energy was not accumulated"

    estimate = float(_sensor_state(hass, entry, "estimated_soc_at_sunrise").state)
    status = _sensor_state(hass, entry, "night_survival_reason").state
    assert estimate > 40.0, f"estimate fell to {estimate}% with the battery at 80%"
    assert "Battery should last" in status
    assert "shortfall" not in status

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

