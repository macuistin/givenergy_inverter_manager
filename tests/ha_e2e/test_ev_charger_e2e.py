"""EV charging cost end to end, using the entity names the myenergi integration really creates."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import CHEAP_NIGHT, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN

# House load 800 W plus the car at 7.2 kW, all imported from the grid in the cheap-rate window.
EV_NIGHT = replace(CHEAP_NIGHT, name="ev_cheap_night", grid_w=-8000.0, load_w=8000.0)

ZAPPI_NO_SERIAL = {
    "sensor.myenergi_zappi_plug_status": "EV Connected",
    "sensor.myenergi_zappi_status": "Boosting",
    "sensor.myenergi_zappi_internal_load_ct1": "7200",
    "sensor.myenergi_zappi_charge_added_session": "3.2",
    "sensor.myenergi_zappi_serial_number": "21637627",
    "select.myenergi_zappi_charge_mode": "Fast",
}


def _state(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return hass.states.get(entity_id)


@pytest.mark.parametrize("scenario", [EV_NIGHT], ids=lambda s: s.name)
async def test_ev_energy_and_cost_accumulate(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    for entity_id, value in ZAPPI_NO_SERIAL.items():
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

    for _ in range(4):
        freezer.tick(timedelta(seconds=60))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator._ev_charger is not None
    assert coordinator._ev_charger.power_entity == "sensor.myenergi_zappi_internal_load_ct1"
    assert float(_state(hass, entry, "ev_power").state) == pytest.approx(7200.0)
    assert coordinator.data.today.zappi_kwh > 0.05
    today = coordinator.data.today
    assert today.zappi_cost > 0.0
    assert today.zappi_cost == pytest.approx(today.total_import_cost * 7200 / 8000, rel=0.02)

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
