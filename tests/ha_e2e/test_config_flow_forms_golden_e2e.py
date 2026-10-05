"""Golden snapshot of every config, reconfigure and options form the frontend receives.

The snapshot holds the serialised schema (field order, keys, defaults, suggested values,
selector configs, sections) plus the step id, errors and description placeholders.
It pins the forms so a refactor of config_flow.py cannot change what the user sees.
If the golden file is missing the test writes it and fails, so a deliberate change to a
form is one reviewed diff of the JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    BATTERY_POWER,
    GRID,
    LOAD,
    MIDDAY,
    SERIAL,
    SOC,
    SOLAR,
    full_config_data,
    set_givtcp_states,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_CURRENCY,
    CONF_DRY_RUN,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_PROVIDER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_RATE_PERIODS,
    CONF_SOLAR_POWER,
    CONF_VERBOSE_LOGGING,
    DOMAIN,
)

GOLDEN = Path(__file__).parent / "golden" / "config_flow_forms.json"

MANUAL_INPUT = {
    "discovered_inverter": "__manual__",
    CONF_SOLAR_POWER: SOLAR,
    CONF_BATTERY_SOC: SOC,
    CONF_BATTERY_POWER: BATTERY_POWER,
    CONF_GRID_POWER: GRID,
    CONF_HOUSE_LOAD: LOAD,
    CONF_BATTERY_CAPACITY: 9.5,
}
ZERO_LENGTH_SLOT = {"name": "Empty", "rate": 0.01, "start": "00:00:00", "end": "00:00:00"}


@pytest.fixture
def scenario():
    return MIDDAY


def _describe(result) -> dict:
    """Serialise a flow result the way the frontend API does."""
    schema = result.get("data_schema")
    fields = cv.to_field_list(schema, custom_serializer=cv.custom_serializer) if schema else []
    return {
        "step_id": result["step_id"],
        "errors": result.get("errors"),
        "placeholders": result.get("description_placeholders"),
        "fields": fields,
    }


def _initial_data(fields: list[dict]) -> dict:
    """What the frontend submits untouched: every default, recursing into sections."""
    data: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            data[field["name"]] = _initial_data(field["schema"])
        elif "default" in field:
            data[field["name"]] = field["default"]
    return data


def _entry(data: dict, options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        options=options or {},
        unique_id=SERIAL,
        version=1,
    )


def _data_without(*keys: str) -> dict:
    data = full_config_data()
    for key in keys:
        data.pop(key)
    return data


async def _setup_forms(hass, prefix: str, first_input: dict | None) -> dict:
    """Walk the setup wizard with defaults, recording the form shown at each step."""
    forms = {}
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    forms[f"{prefix}.inverter"] = _describe(result)
    result = await flow.async_configure(result["flow_id"], user_input=first_input)
    for step in ("tariff", "forecast", "immersion", "ev", "battery", "confirm"):
        forms[f"{prefix}.{step}"] = _describe(result)
        if step == "tariff":
            invalid = await flow.async_configure(
                result["flow_id"], user_input={"rate_period_3": ZERO_LENGTH_SLOT, CONF_CURRENCY: "EUR"}
            )
            forms[f"{prefix}.tariff_with_error"] = _describe(invalid)
        if step != "confirm":
            result = await flow.async_configure(result["flow_id"], user_input={})
    flow.async_abort(result["flow_id"])
    return forms


async def _options_form(hass, entry: MockConfigEntry, submit: dict | None = None) -> dict:
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if submit is not None:
        payload = {**_initial_data(_describe(result)["fields"]), **submit}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=payload
        )
    description = _describe(result)
    hass.config_entries.options.async_abort(result["flow_id"])
    return description


async def _reconfigure_form(hass, entry: MockConfigEntry, submit: dict | None = None) -> dict:
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    if submit is not None:
        payload = {**_initial_data(_describe(result)["fields"]), **submit}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=payload
        )
    description = _describe(result)
    hass.config_entries.flow.async_abort(result["flow_id"])
    return description


async def _collect_forms(hass) -> dict:
    forms: dict = {}
    forms.update(await _setup_forms(hass, "setup_manual", MANUAL_INPUT))
    set_givtcp_states(hass, MIDDAY)
    forms.update(
        await _setup_forms(hass, "setup_auto", {"discovered_inverter": SERIAL, CONF_BATTERY_CAPACITY: 9.5})
    )

    overrides = {
        CONF_EXPORT_RATE: 0.0,
        CONF_CURRENCY: "GBP",
        CONF_CHEAP_RATE_FLOOR_SOC: 0,
        CONF_BATTERY_CAPACITY: 13.5,
        CONF_BATTERY_COST: 4500,
        CONF_DRY_RUN: True,
        CONF_VERBOSE_LOGGING: True,
        CONF_FORECAST_ENTITY: "",
        CONF_FORECAST_PROVIDER: "forecast_solar",
        CONF_BASE_RATE_NAME: "Standard",
        CONF_RATE_PERIODS: [],
    }
    forms["reconfigure_data_only"] = await _reconfigure_form(hass, _entry(full_config_data()))
    forms["reconfigure_with_options"] = await _reconfigure_form(
        hass, _entry(full_config_data(), overrides)
    )
    forms["reconfigure_with_error"] = await _reconfigure_form(
        hass, _entry(full_config_data(), overrides), submit={"rate_period_2": ZERO_LENGTH_SLOT}
    )
    forms["options_data_only"] = await _options_form(hass, _entry(full_config_data()))
    forms["options_no_optional_data"] = await _options_form(
        hass,
        _entry(
            _data_without(
                "forecast_provider", "forecast_entity", "carbon_intensity_entity", "base_rate_name"
            )
        ),
    )
    forms["options_with_overrides"] = await _options_form(hass, _entry(full_config_data(), overrides))
    forms["options_with_error"] = await _options_form(
        hass,
        _entry(full_config_data()),
        submit={"rate_period_1": ZERO_LENGTH_SLOT},
    )
    return json.loads(json.dumps(forms))


async def test_forms_match_the_golden_snapshot(hass):
    forms = await _collect_forms(hass)
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(forms, indent=1, ensure_ascii=False) + "\n")
        pytest.fail(f"golden file written to {GOLDEN}; review and commit it")
    expected = json.loads(GOLDEN.read_text())
    assert list(forms) == list(expected)
    for name in expected:
        assert forms[name] == expected[name], name
