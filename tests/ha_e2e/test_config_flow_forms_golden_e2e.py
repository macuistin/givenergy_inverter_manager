"""Golden snapshot of every config, reconfigure and options form the frontend receives.

The snapshot holds the serialised schema (field order, keys, defaults, suggested values,
selector configs, sections) plus the step id, last_step, errors and description placeholders,
for the setup wizard, reconfigure (the inverter connection) and the options wizard.
It pins the forms so a refactor of the wizards cannot change what the user sees.
If the golden file is missing the test writes it and fails, so a deliberate change to a
form is one reviewed diff of the JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    BATTERY_POWER,
    FORECAST,
    GRID,
    LOAD,
    MIDDAY,
    SERIAL,
    SOC,
    SOLAR,
    full_config_data,
    serialise_schema,
    set_givtcp_states,
)
from homeassistant.config_entries import SOURCE_USER
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import open_options, submit, walk_options_forms

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CURRENCY,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_RATE_PERIODS,
    CONF_SOLAR_POWER,
    DOMAIN,
)

GOLDEN = Path(__file__).parent / "golden" / "config_flow_forms.json"

FIVE = {
    CONF_SOLAR_POWER: SOLAR,
    CONF_BATTERY_SOC: SOC,
    CONF_BATTERY_POWER: BATTERY_POWER,
    CONF_GRID_POWER: GRID,
    CONF_HOUSE_LOAD: LOAD,
}
ZERO_LENGTH_SLOT = {"name": "Empty", "rate": 0.01, "start": "00:00:00", "end": "00:00:00"}
TARIFF = {"base_rate": 0.3, "export_rate": 0.1}
ROWS = {"rate_period_1": {"rate": 0.12}, "rate_period_2": {"rate": 0.2}}


@pytest.fixture
def scenario():
    return MIDDAY


@pytest.fixture(autouse=True)
def _frozen_day(freezer):
    """Pin today's date, which the confirm step prints (Tariff last confirmed: ... to <today>)."""
    freezer.move_to(MIDDAY.frozen_utc)


def _describe(result) -> dict:
    """Serialise a flow result the way the frontend API does."""
    schema = result.get("data_schema")
    fields = serialise_schema(schema) if schema else []
    return {
        "step_id": result["step_id"],
        "last_step": result.get("last_step"),
        "errors": result.get("errors"),
        "placeholders": result.get("description_placeholders"),
        "fields": fields,
    }


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


async def _setup_forms(hass, prefix: str) -> dict:
    """Walk the setup wizard with every page ticked, recording each form and each error."""
    forms = {}
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    forms[f"{prefix}.system"] = _describe(result)
    offered = next(f for f in serialise_schema(result["data_schema"]) if f["name"] == "pages")
    pages = offered["selector"]["select"]["options"]
    result = await submit(flow, result, pages=pages)
    if result["step_id"] == "inverter_entities":
        forms[f"{prefix}.inverter_entities"] = _describe(result)
        result = await submit(flow, result, **FIVE)
    while result["step_id"] != "confirm":
        step = result["step_id"]
        forms[f"{prefix}.{step}"] = _describe(result)
        values = {}
        if step == "tariff":
            invalid = await submit(flow, result, base_rate=0, export_rate=0.1)
            forms[f"{prefix}.tariff_with_error"] = _describe(invalid)
            values = {**TARIFF, "rate_count": "2"}
        if step == "tariff_rates":
            invalid = await submit(flow, result, rate_period_1=ZERO_LENGTH_SLOT, **{"rate_period_2": {"rate": 0.2}})
            forms[f"{prefix}.tariff_rates_with_error"] = _describe(invalid)
            values = ROWS
        if step == "hot_water":
            # A warning shows the form once more with a note, then the same submission goes on.
            values = {"alt_heat": {"alt_heat_enabled": True}}
            result = await submit(flow, result, **values)
            forms[f"{prefix}.hot_water_with_warning"] = _describe(result)
        result = await submit(flow, result, **values)
    forms[f"{prefix}.confirm"] = _describe(result)
    flow.async_abort(result["flow_id"])
    return forms


async def _options_forms(hass, entry: MockConfigEntry, prefix: str) -> dict:
    """Every form of the options wizard with every page and tariff screen ticked."""
    entry.add_to_hass(hass)
    forms = {}
    for step_id, form in (await walk_options_forms(hass, entry)).items():
        forms[f"{prefix}.{step_id}"] = _describe(form["result"])
    return forms


async def _options_errors(hass, entry: MockConfigEntry, prefix: str) -> dict:
    entry.add_to_hass(hass)
    forms = {}
    manager = hass.config_entries.options
    result = await open_options(hass, entry, {"tariff": {}, "tariff_rates": {}})
    result = await submit(manager, result, rate_count="3", edit_rates=True)
    bad = await submit(manager, result, rate_period_3=ZERO_LENGTH_SLOT)
    forms[f"{prefix}.tariff_rates_with_error"] = _describe(bad)
    manager.async_abort(bad["flow_id"])
    result = await open_options(hass, entry, {"tariff": {}, "schedule_change": {}})
    result = await submit(manager, result, schedule_change=True)
    bad = await submit(manager, result, effective_from="2000-01-01")
    forms[f"{prefix}.schedule_change_with_error"] = _describe(bad)
    manager.async_abort(bad["flow_id"])
    return forms


async def _reconfigure_forms(hass, entry: MockConfigEntry, prefix: str) -> dict:
    entry.add_to_hass(hass)
    forms = {}
    flow = hass.config_entries.flow
    result = await entry.start_reconfigure_flow(hass)
    forms[f"{prefix}.reconfigure"] = _describe(result)
    manual = await submit(flow, result, source="manual")
    forms[f"{prefix}.reconfigure_manual"] = _describe(manual)
    bad = await submit(flow, manual, **{**FIVE, CONF_SOLAR_POWER: "sensor.not_there"})
    forms[f"{prefix}.reconfigure_manual_with_error"] = _describe(bad)
    flow.async_abort(bad["flow_id"])
    return forms


async def _collect_forms(hass) -> dict:
    forms: dict = {}
    # Nothing discovered: the first screen asks for the capacity and the five entities.
    for entity_id in list(hass.states.async_entity_ids()):
        hass.states.async_remove(entity_id)
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    forms["setup_manual.system"] = _describe(result)
    result = await submit(flow, result, pages=[])
    forms["setup_manual.inverter_entities"] = _describe(result)
    flow.async_abort(result["flow_id"])

    set_givtcp_states(hass, MIDDAY)
    forms.update(await _setup_forms(hass, "setup_auto"))
    hass.states.async_remove(FORECAST)
    forms.update(await _setup_forms(hass, "setup_auto_no_forecast"))
    # GivTCP holds rates its user changed: the tariff pages start from them.
    for suffix, value in (("day_rate", 0.2918), ("night_rate", 0.1432), ("export_rate", 0.1)):
        hass.states.async_set(f"sensor.givtcp_{SERIAL}_{suffix}", value)
    forms.update(await _setup_forms(hass, "setup_auto_with_givtcp_rates"))
    for suffix in ("day_rate", "night_rate", "export_rate"):
        hass.states.async_remove(f"sensor.givtcp_{SERIAL}_{suffix}")

    overrides = {
        CONF_EXPORT_RATE: 0.0,
        CONF_CURRENCY: "GBP",
        CONF_BATTERY_CAPACITY: 13.5,
        CONF_BATTERY_COST: 4500,
        CONF_BASE_RATE_NAME: "Standard",
        CONF_RATE_PERIODS: [],
        CONF_FORECAST_ENTITY: "",
    }
    forms.update(await _reconfigure_forms(hass, _entry(full_config_data()), "reconfigure"))
    forms.update(await _options_forms(hass, _entry(full_config_data()), "options_data_only"))
    forms.update(
        await _options_forms(
            hass,
            _entry(_data_without("forecast_entity", "carbon_intensity_entity", "base_rate_name")),
            "options_no_optional_data",
        )
    )
    forms.update(
        await _options_forms(hass, _entry(full_config_data(), overrides), "options_with_overrides")
    )
    forms.update(await _options_errors(hass, _entry(full_config_data()), "options"))
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
