"""The forecast's own shape reaches the plan and the sensor, inside a real Home Assistant."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FORECAST, MIDDAY
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "forecast" / "solcast_tomorrow.json").read_text()
)
ATTRIBUTES = FIXTURE["attributes"]

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


def _plan_forecast_sensor(hass, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_solar_forecast_kwh_today"
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


async def _refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_a_solcast_sensor_with_detail_gives_the_plan_its_shape(hass, loaded_entry):
    hass.states.async_set(FORECAST, "33.5765", ATTRIBUTES)
    await _refresh(hass, loaded_entry)

    decision = loaded_entry.runtime_data.data.charge_decision
    assert "Solar follows your forecast's shape." in decision.reason
    sensor = _plan_forecast_sensor(hass, loaded_entry)
    assert sensor.attributes["solar_profile_source"] == "forecast"


async def test_a_sensor_with_totals_only_keeps_the_standard_curve(hass, loaded_entry):
    totals_only = {k: v for k, v in ATTRIBUTES.items() if not k.startswith("detailed")}
    hass.states.async_set(FORECAST, "33.5765", totals_only)
    await _refresh(hass, loaded_entry)

    decision = loaded_entry.runtime_data.data.charge_decision
    assert "forecast's shape" not in decision.reason
    assert _plan_forecast_sensor(hass, loaded_entry).attributes["solar_profile_source"] == (
        "standard curve"
    )


async def test_the_shape_follows_the_sensor_when_the_detail_is_switched_off_later(
    hass, loaded_entry
):
    hass.states.async_set(FORECAST, "33.5765", ATTRIBUTES)
    await _refresh(hass, loaded_entry)
    assert loaded_entry.runtime_data.data.solar_shape_used is True

    hass.states.async_set(FORECAST, "33.5765", {"estimate10": 12.0})
    await _refresh(hass, loaded_entry)

    assert loaded_entry.runtime_data.data.solar_shape_used is False
