"""Options flow against a real flow manager, including the schema the frontend receives."""

from __future__ import annotations

import pytest
from conftest import FORECAST, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_FORECAST_CONSERVATISM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_PROVIDER,
    CONF_RATE_PERIODS,
    DOMAIN,
)

OPTIONAL_ENTITY_KEYS = (
    CONF_FORECAST_PROVIDER,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_ENTITY_D2,
    CONF_CARBON_INTENSITY_ENTITY,
)


@pytest.fixture
def scenario():
    """These tests do not depend on the time of day."""
    return MIDDAY


@pytest.fixture(params=[True, False], ids=["forecast_configured", "no_forecast_configured"])
def config_entry(request):
    """Entry with, or without, forecast and carbon entities in its stored data."""
    data = full_config_data()
    if not request.param:
        for key in OPTIONAL_ENTITY_KEYS:
            data.pop(key)
        data.pop(CONF_FORECAST_CONSERVATISM)
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )


def _serialise(result) -> list[dict]:
    """Convert the form schema the way the frontend API does."""
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert isinstance(fields, list), f"form schema did not serialise: {fields!r}"
    return fields


def _initial_data(fields: list[dict]) -> dict:
    """Mimic the frontend: pre-fill every field that has a default, recursing into sections."""
    data: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            data[field["name"]] = _initial_data(field["schema"])
        elif "default" in field:
            data[field["name"]] = field["default"]
    return data


def frontend_payload(result, **section_overrides: dict) -> dict:
    """What the frontend submits when the user changes nothing but the given section values.

    Fields without a default (the optional entity selectors) are omitted, which is how an
    empty selection reaches the flow.
    """
    payload = _initial_data(_serialise(result))
    for name, values in section_overrides.items():
        payload[name] = {**payload.get(name, {}), **values}
    return payload


async def test_options_form_renders_and_serialises(hass, loaded_entry):
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _serialise(result)
    hass.config_entries.options.async_abort(result["flow_id"])


async def test_options_accept_empty_forecast_and_carbon_selection(hass, loaded_entry):
    """(d) Submitting with no forecast or carbon entity selected is accepted."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    payload = frontend_payload(result)
    assert "forecast_entity" not in payload["forecast_settings"]
    assert "carbon_intensity_entity" not in payload["forecast_settings"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=payload
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    for key in OPTIONAL_ENTITY_KEYS:
        assert not loaded_entry.options[key]
    # The update listener reloads the entry. It must come back LOADED, not unavailable.
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.last_update_success


async def test_options_form_reopens_after_empty_submission(hass, loaded_entry):
    """The stored empty values must not break rendering the form a second time."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=frontend_payload(result)
    )
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert _serialise(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=frontend_payload(result)
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_options_save_tariff_change_takes_effect(hass, loaded_entry):
    """A changed rate in the options flow reaches the entry options and survives the reload."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    user_input = frontend_payload(result, tariff_settings={"export_rate": 0.21})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=user_input
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["export_rate"] == pytest.approx(0.21)
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.21)
    # The default rate periods are carried through when the slots are left alone.
    assert [p["name"] for p in loaded_entry.options[CONF_RATE_PERIODS]] == ["Night", "Nightboost"]
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_cleared_forecast_stays_cleared_when_form_reopens(hass, loaded_entry):
    """After clearing the forecast entity, the next options form must not suggest the old one."""
    # Select a forecast entity through the options flow.
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    payload = frontend_payload(result, forecast_settings={CONF_FORECAST_ENTITY: FORECAST})
    await hass.config_entries.options.async_configure(result["flow_id"], user_input=payload)
    await hass.async_block_till_done()
    assert loaded_entry.options[CONF_FORECAST_ENTITY] == FORECAST

    # Clear it again: the frontend omits an emptied optional selector.
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    payload = frontend_payload(result)
    payload["forecast_settings"].pop(CONF_FORECAST_ENTITY, None)
    await hass.config_entries.options.async_configure(result["flow_id"], user_input=payload)
    await hass.async_block_till_done()
    assert not loaded_entry.options[CONF_FORECAST_ENTITY]

    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    forecast_section = next(f for f in _serialise(result) if f.get("name") == "forecast_settings")
    suggested = {
        f["name"]: f.get("description", {}).get("suggested_value")
        for f in forecast_section["schema"]
    }
    assert not suggested.get(CONF_FORECAST_ENTITY), suggested


async def test_zero_threshold_survives_reopening_the_form(hass, loaded_entry):
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    payload = frontend_payload(result, threshold_settings={"cheap_rate_floor_soc": 0})
    await hass.config_entries.options.async_configure(result["flow_id"], user_input=payload)
    await hass.async_block_till_done()
    assert loaded_entry.options["cheap_rate_floor_soc"] == 0

    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    threshold_section = next(f for f in _serialise(result) if f.get("name") == "threshold_settings")
    defaults = {f["name"]: f.get("default") for f in threshold_section["schema"]}
    assert defaults["cheap_rate_floor_soc"] == 0
