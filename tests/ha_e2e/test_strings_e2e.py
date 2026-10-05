"""Every field in every form the real flows build has a label and help text in the strings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv

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
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
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


async def _collect_forms(hass, flow_manager, flow_id, result) -> list[tuple[str, list[dict]]]:
    """Submit empty input to every form, recording (step_id, fields) as it goes."""
    forms = []
    while result["type"] is FlowResultType.FORM:
        forms.append((result["step_id"], _fields(result)))
        result = await flow_manager.async_configure(flow_id, user_input={})
    return forms


async def _assert_all_labelled(forms, kind: str) -> None:
    assert forms
    for file_name in STRING_FILES:
        strings = json.loads((_COMPONENT / file_name).read_text(encoding="utf-8"))
        problems = []
        for step_id, fields in forms:
            problems += _missing(strings, kind, step_id, fields)
        assert not problems, f"{file_name} is missing:\n" + "\n".join(problems)


async def test_setup_wizard_forms_are_fully_labelled(hass, hass_in_scenario, service_calls):
    """Discovered inverter path: inverter, tariff, forecast, immersion, EV and battery."""
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "inverter"
    assert CONF_SOLAR_POWER not in {f["name"] for f in _fields(result)}
    forms = await _collect_forms(hass, flow, result["flow_id"], result)
    assert [step for step, _ in forms][:3] == ["inverter", "tariff", "forecast"]
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await _assert_all_labelled(forms, "config")


async def test_manual_inverter_form_is_fully_labelled(hass):
    """No GivTCP entities: the manual form with the five entity selectors."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    fields = _fields(result)
    assert {CONF_SOLAR_POWER, CONF_BATTERY_SOC} <= {f["name"] for f in fields}
    await _assert_all_labelled([("inverter", fields)], "config")
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_reconfigure_form_is_fully_labelled(hass, loaded_entry):
    result = await loaded_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    await _assert_all_labelled([("reconfigure", _fields(result))], "config")
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_options_form_is_fully_labelled(hass, loaded_entry):
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["step_id"] == "init"
    await _assert_all_labelled([("init", _fields(result))], "options")
    hass.config_entries.options.async_abort(result["flow_id"])
