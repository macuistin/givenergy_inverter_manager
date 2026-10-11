"""Helpers that drive the setup and options wizards the way the frontend does.

The frontend pre-fills every field that has a default, recursing into sections, and omits an
optional field that has none. `payload` builds that submission from the serialised schema and
applies the values a test wants to change. Not collected as tests (the name has no `test_`
prefix).
"""

from __future__ import annotations

from typing import Any

from conftest import serialise_schema
from homeassistant.data_entry_flow import FlowResultType


def initial_data(fields: list[dict]) -> dict[str, Any]:
    """What the frontend submits untouched: every default and suggested value, recursing into
    sections. A field with neither is left out, as the frontend leaves an empty one out."""
    data: dict[str, Any] = {}
    for field in fields:
        suggested = (field.get("description") or {}).get("suggested_value")
        if field.get("type") == "expandable":
            data[field["name"]] = initial_data(field["schema"])
        elif "default" in field:
            data[field["name"]] = field["default"]
        elif suggested is not None:
            data[field["name"]] = suggested
    return data


def serialised(result) -> list[dict]:
    fields = serialise_schema(result["data_schema"])
    assert isinstance(fields, list), f"form schema did not serialise: {fields!r}"
    return fields


def every_field(fields: list[dict]) -> list[dict]:
    """The fields of a serialised form with the ones inside sections included."""
    found: list[dict] = []
    for field in fields:
        if field.get("type") == "expandable":
            found += every_field(field["schema"])
        else:
            found.append(field)
    return found


def field_names(result) -> list[str]:
    """The top-level field names of a form, in order, sections as their own name."""
    return [field["name"] for field in serialised(result)]


class Only(dict):
    """A section submitted with exactly these values, not merged into the pre-filled ones."""


def _apply(data: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """*overrides* over the pre-filled *data*. A plain dict for a section is merged into the
    section's values, an Only replaces them, and a value of None leaves the key out."""
    for name, value in overrides.items():
        if isinstance(value, Only):
            data[name] = dict(value)
        elif isinstance(value, dict) and isinstance(data.get(name), dict):
            data[name] = {**data[name], **value}
        else:
            data[name] = value
    return data


def payload(result, **overrides: Any) -> dict[str, Any]:
    """The submission for *result*: the defaults, then *overrides*."""
    return _drop_none(_apply(initial_data(serialised(result)), overrides))


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {
        k: _drop_none(v) if isinstance(v, dict) else v for k, v in data.items() if v is not None
    }


async def submit(manager, result, **overrides: Any):
    """Submit *result*'s form with its defaults and *overrides*."""
    return await manager.async_configure(result["flow_id"], user_input=payload(result, **overrides))


TARIFF_ON_OPTIONS = {"tariff_rates": "edit_rates", "bill": "edit_bill", "schedule_change": "schedule_change"}
PAGE_OF_STEP = {
    "tariff": "tariff",
    "tariff_rates": "tariff",
    "bill": "tariff",
    "schedule_change": "tariff",
    "battery": "battery",
    "forecast": "forecast",
    "hot_water": "hot_water",
    "ev": "ev",
}


MAX_SCREENS = 30


async def open_options(hass, entry, steps: dict[str, dict[str, Any]]):
    """Start the options wizard, tick the pages of *steps* and return the first page's form."""
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["step_id"] == "init", result
    pages = sorted({PAGE_OF_STEP[step] for step in steps})
    return await manager.async_configure(result["flow_id"], user_input={"pages": pages})


async def options_wizard(hass, entry, steps: dict[str, dict[str, Any]], *, confirm: bool = True):
    """Run the options wizard for *entry* through the steps in *steps* and return the result.

    *steps* maps a step id to the values to submit on it (an empty dict accepts the defaults).
    The pages ticked on the first screen are the pages of those steps, and the tariff screen's
    tick boxes follow the tariff steps listed. A step the wizard shows that is not listed fails
    the test. The confirm step is submitted when it is shown and *confirm* is true.
    """
    result = await open_options(hass, entry, steps)
    manager = hass.config_entries.options
    seen: list[str] = []
    while result["type"] is FlowResultType.FORM:
        step_id = result["step_id"]
        seen.append(step_id)
        if result.get("errors") or len(seen) > MAX_SCREENS:
            return result
        if step_id == "confirm":
            if not confirm:
                return result
            result = await manager.async_configure(result["flow_id"], user_input={})
            continue
        assert step_id in steps, f"unexpected step {step_id}, wanted {list(steps)}, saw {seen}"
        values = dict(steps[step_id])
        if step_id == "tariff":
            for sub, tick in TARIFF_ON_OPTIONS.items():
                if sub in steps:
                    values.setdefault(tick, True)
        result = await submit(manager, result, **values)
    await hass.async_block_till_done()
    return result


async def walk_options_forms(hass, entry) -> dict[str, dict]:
    """Every form of the options wizard with every page and every tariff screen ticked.

    Returns the serialised fields and the result by step id, each submitted untouched, and aborts
    before the write. A form is described as {"fields": [...], "result": result}.
    """
    manager = hass.config_entries.options
    forms: dict[str, dict] = {}
    result = await manager.async_init(entry.entry_id)
    forms["init"] = {"fields": serialised(result), "result": result}
    pages = ["tariff", "battery", "forecast", "hot_water", "ev"]
    result = await manager.async_configure(result["flow_id"], user_input={"pages": pages})
    while result["type"] is FlowResultType.FORM:
        step_id = result["step_id"]
        forms[step_id] = {"fields": serialised(result), "result": result}
        if step_id == "confirm":
            manager.async_abort(result["flow_id"])
            break
        extra = dict.fromkeys(TARIFF_ON_OPTIONS.values(), True) if step_id == "tariff" else {}
        if step_id == "tariff":
            extra["rate_count"] = "1"
        if step_id == "tariff_rates":
            extra = {"rate_period_1": {"rate": 0.1}}
        result = await submit(manager, result, **extra)
    return forms
