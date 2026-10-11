"""Every field in every form the real flows build has a label and help text in the strings."""

from __future__ import annotations

import json
import string
from pathlib import Path

import pytest
from conftest import MIDDAY, serialise_schema
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from wizard_support import submit, walk_options_forms

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_SOC,
    CONF_SOLAR_POWER,
    DOMAIN,
)

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / DOMAIN
STRING_FILES = ("strings.json", "translations/en.json")


@pytest.fixture
def scenario():
    return MIDDAY


def _fields(result) -> list[dict]:
    fields = serialise_schema(result["data_schema"])
    assert isinstance(fields, list), fields
    return fields


def _missing(strings: dict, kind: str, step_id: str, fields: list[dict]) -> list[str]:
    """Return a description of every field without a label or help text."""
    step = strings[kind]["step"].get(step_id)
    if step is None:
        return [f"{kind}.{step_id}: step has no strings"]
    problems: list[str] = []
    for field in fields:
        name = field["name"]
        if field.get("type") == "expandable":
            section = step.get("sections", {}).get(name, {})
            where = f"{kind}.{step_id}.sections.{name}"
            if not section.get("name"):
                problems.append(f"{where}: no name")
            if not section.get("description"):
                problems.append(f"{where}: no description")
            for sub in field["schema"]:
                for block in ("data", "data_description"):
                    if not section.get(block, {}).get(sub["name"]):
                        problems.append(f"{where}.{block}.{sub['name']}")
        else:
            for block in ("data", "data_description"):
                if not step.get(block, {}).get(name):
                    problems.append(f"{kind}.{step_id}.{block}.{name}")
    return problems


def _placeholders_in(text: str) -> set[str]:
    """The {name} placeholders a description uses."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _unfilled_placeholders(strings: dict, kind: str, result) -> list[str]:
    """Placeholders in the step's title or description that the flow did not supply."""
    step = strings[kind]["step"].get(result["step_id"], {})
    used = _placeholders_in(step.get("description", "")) | _placeholders_in(step.get("title", ""))
    given = set(result.get("description_placeholders") or {})
    return sorted(f"{kind}.{result['step_id']}: {name}" for name in used - given)


async def _assert_all_labelled(forms, kind: str) -> None:
    assert forms
    for file_name in STRING_FILES:
        strings = json.loads((_COMPONENT / file_name).read_text(encoding="utf-8"))
        problems = []
        for result in forms:
            problems += _missing(strings, kind, result["step_id"], _fields(result))
            problems += _unfilled_placeholders(strings, kind, result)
        assert not problems, f"{file_name} is missing:\n" + "\n".join(problems)


async def _walk_setup(hass, ticked: list[str], user_inputs: dict[str, dict]) -> list:
    """The setup wizard through every form, each submitted with its defaults and *user_inputs*."""
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    forms = []
    while result["type"] is FlowResultType.FORM:
        forms.append(result)
        step = result["step_id"]
        values = dict(user_inputs.get(step, {}))
        if step == "system":
            values["pages"] = ticked
        result = await submit(flow, result, **values)
    return forms


async def test_every_setup_form_is_fully_labelled(hass, hass_in_scenario, service_calls):
    """Discovered inverter, every page ticked, time-of-day rates, so every setup form is shown."""
    hass.states.async_remove("sensor.energy_production_tomorrow")
    forms = await _walk_setup(
        hass,
        ["tariff", "forecast", "hot_water"],
        {"tariff": {"base_rate": 0.3, "export_rate": 0.1, "rate_count": "2"},
         "tariff_rates": {f"rate_period_{i}": {"rate": 0.1 * i} for i in (1, 2)}},
    )
    await hass.async_block_till_done()
    assert [r["step_id"] for r in forms] == [
        "system", "tariff", "tariff_rates", "forecast", "hot_water", "confirm",
    ]
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await _assert_all_labelled(forms, "config")


async def test_the_manual_inverter_forms_are_fully_labelled(hass):
    """No GivTCP entities: the system form and the form with the five entity selectors."""
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    system = result
    assert {f["name"] for f in _fields(system)} >= {"battery_capacity_kwh", "pages"}
    result = await submit(flow, result, pages=[])
    assert result["step_id"] == "inverter_entities"
    assert {CONF_SOLAR_POWER, CONF_BATTERY_SOC} <= {f["name"] for f in _fields(result)}
    await _assert_all_labelled([system, result], "config")
    flow.async_abort(result["flow_id"])


async def test_both_reconfigure_forms_are_fully_labelled(hass, loaded_entry):
    result = await loaded_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    forms = [result]
    result = await submit(hass.config_entries.flow, result, source="manual")
    assert result["step_id"] == "reconfigure_manual"
    forms.append(result)
    await _assert_all_labelled(forms, "config")
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_every_options_form_is_fully_labelled(hass, loaded_entry):
    forms = await walk_options_forms(hass, loaded_entry)
    assert set(forms) >= {
        "init", "tariff", "tariff_rates", "bill", "schedule_change",
        "battery", "forecast", "hot_water", "ev", "confirm",
    }
    await _assert_all_labelled([form["result"] for form in forms.values()], "options")


async def test_every_error_the_flows_can_return_has_text_in_both_files(hass, loaded_entry):
    from custom_components.givenergy_inverter_manager.core.wizard_model import ERROR_KEYS

    for file_name in STRING_FILES:
        strings = json.loads((_COMPONENT / file_name).read_text(encoding="utf-8"))
        options_errors = set(strings["options"]["error"])
        config_errors = set(strings["config"]["error"])
        missing = [key for key in ERROR_KEYS if key not in options_errors | config_errors]
        assert not missing, f"{file_name} has no text for {missing}"
        setup_only = {"missing_entities"}
        assert setup_only <= config_errors
