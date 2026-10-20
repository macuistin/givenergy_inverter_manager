"""The setup wizard's connection check, and the paths that only a real flow reaches.

The checks run before the entry exists, so a wrong entity is refused on the screen and never
reaches a loaded integration.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import FORECAST_D2, MIDDAY
from homeassistant.data_entry_flow import FlowResultType
from setup_support import FIVE, TARIFF, finish, manager, only_inverter_states, start, unload
from wizard_support import serialised, submit

from custom_components.givenergy_inverter_manager.const import (
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_FORECAST_ENTITY_D2,
    CONF_GRID_POWER,
)
from custom_components.givenergy_inverter_manager.core.seasons import season_defaults
from custom_components.givenergy_inverter_manager.core.wizard_model import Mode, PageContext
from custom_components.givenergy_inverter_manager.wizard.schemas import charge_planning_schema


@pytest.fixture
def scenario():
    return MIDDAY


async def _entity_screen(hass):
    only_inverter_states(hass)
    result = await start(hass)
    result = await submit(manager(hass), result, pages=[])
    assert result["step_id"] == "inverter_entities"
    return result


async def test_the_entity_screen_refuses_an_entity_that_does_not_exist(
    hass, hass_in_scenario, service_calls
):
    result = await _entity_screen(hass)

    result = await submit(manager(hass), result, **{**FIVE, CONF_GRID_POWER: "sensor.not_there"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "inverter_entities"
    assert result["errors"] == {"base": "missing_entities"}
    suggested = {
        f["name"]: (f.get("description") or {}).get("suggested_value") for f in serialised(result)
    }
    assert suggested[CONF_GRID_POWER] == "sensor.not_there"
    manager(hass).async_abort(result["flow_id"])


async def test_the_entity_screen_refuses_an_entity_that_is_unavailable(
    hass, hass_in_scenario, service_calls
):
    result = await _entity_screen(hass)
    hass.states.async_set(FIVE[CONF_GRID_POWER], "unavailable")

    result = await submit(manager(hass), result, **FIVE)

    assert result["errors"] == {"base": "missing_entities"}
    manager(hass).async_abort(result["flow_id"])


async def test_entities_chosen_by_hand_carry_on_to_the_ticked_pages(
    hass, hass_in_scenario, service_calls
):
    only_inverter_states(hass)
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])
    assert result["step_id"] == "inverter_entities"
    result = await submit(manager(hass), result, **FIVE)

    assert result["step_id"] == "tariff"
    while result["type"] is FlowResultType.FORM and result["step_id"] != "confirm":
        result = await submit(manager(hass), result, **(TARIFF if result["step_id"] == "tariff" else {}))
    entry = await finish(hass, result)
    try:
        assert entry.unique_id == "manual"
    finally:
        await unload(hass, entry)


async def test_a_forecast_with_a_day_after_sensor_stores_both(hass, hass_in_scenario, service_calls):
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_tomorrow", "20")
    hass.states.async_set(FORECAST_D2, "18")
    result = await start(hass)

    result = await submit(manager(hass), result, pages=[])
    entry = await finish(hass, result)
    try:
        assert entry.data[CONF_FORECAST_ENTITY_D2] == FORECAST_D2
    finally:
        await unload(hass, entry)


def test_the_charge_planning_page_offers_the_latitude_months_when_none_are_saved():
    ctx = PageContext(Mode.SETUP, date(2026, 10, 20), latitude=53.3)

    fields = {str(marker): marker.default() for marker in charge_planning_schema(ctx).schema}

    expected = season_defaults(53.3)
    assert fields[CONF_CHARGE_WINTER_MONTHS] == [str(m) for m in expected[CONF_CHARGE_WINTER_MONTHS]]
    assert fields[CONF_CHARGE_SHOULDER_MONTHS] == [
        str(m) for m in expected[CONF_CHARGE_SHOULDER_MONTHS]
    ]
