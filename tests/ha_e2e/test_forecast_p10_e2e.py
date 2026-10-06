"""A Solcast forecast sensor carries its own P10, so the pessimistic forecast needs no setup."""

from __future__ import annotations

import pytest
from conftest import FORECAST, MIDDAY, full_config_data
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY_P10, DOMAIN

SOLCAST_ATTRIBUTES = {
    "unit_of_measurement": "kWh",
    "device_class": "energy",
    "estimate": 38.1,
    "estimate10": 19.3,
    "estimate90": 40.9,
}


@pytest.fixture
def scenario():
    return MIDDAY


async def _loaded(hass, *, with_attribute: bool):
    attributes = SOLCAST_ATTRIBUTES if with_attribute else {"unit_of_measurement": "kWh"}
    hass.states.async_set(FORECAST, "38.1", attributes)
    data = full_config_data()
    data.pop(CONF_FORECAST_ENTITY_P10)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id="ab1234g567",
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    return entry


async def test_the_p10_attribute_is_blended_without_a_p10_sensor(hass_in_scenario, service_calls):
    entry = await _loaded(hass_in_scenario, with_attribute=True)
    decision = entry.runtime_data.data.charge_decision
    assert "no P10 forecast" not in decision.reason
    assert "P10/P50 blend" in decision.reason
    assert decision.forecast_kwh < 38.1


async def test_without_the_attribute_or_a_sensor_conservatism_is_unused(
    hass_in_scenario, service_calls
):
    entry = await _loaded(hass_in_scenario, with_attribute=False)
    decision = entry.runtime_data.data.charge_decision
    assert "no P10 forecast so conservatism is unused" in decision.reason
