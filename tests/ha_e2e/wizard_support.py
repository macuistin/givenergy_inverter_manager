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


PAGE_OF_STEP = {
    "tariff": "tariff",
    "tariff_rates": "tariff",
    "bill": "tariff",
    "schedule_change": "tariff",
    "tariff_reviewed": "tariff",
    "battery": "battery",
    "charge_planning": "charge_planning",
    "forecast": "charge_planning",
    "hot_water": "hot_water",
    "ev": "ev",
}
# The main menu opens each page by its own step id, and the tariff by its menu.
MENU_OPTION_OF_PAGE = {
    "tariff": "tariff_menu",
    "battery": "battery",
    "charge_planning": "charge_planning",
    "hot_water": "hot_water",
    "ev": "ev",
}
TARIFF_ORDER = ("tariff", "tariff_rates", "bill", "schedule_change", "tariff_reviewed")
PAGE_ORDER = ("tariff", "battery", "charge_planning", "hot_water", "ev")


MAX_SCREENS = 30


async def choose(manager, result, option: str):
    """Pick *option* from the menu *result* shows."""
    assert result["type"] is FlowResultType.MENU, result
    assert option in result["menu_options"], (option, result["menu_options"])
    return await manager.async_configure(result["flow_id"], user_input={"next_step_id": option})


async def open_page(hass, entry, step: str):
    """Start Configure and open the screen *step*, through the tariff menu for a tariff screen."""
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["step_id"] == "init", result
    page = PAGE_OF_STEP[step]
    result = await choose(manager, result, MENU_OPTION_OF_PAGE[page])
    if page == "tariff":
        result = await choose(manager, result, step)
    return result


async def open_options(hass, entry, steps: dict[str, dict[str, Any]]):
    """Start Configure and open the first screen of *steps*, in menu order."""
    first = min(steps, key=lambda step: (PAGE_ORDER.index(PAGE_OF_STEP[step]), _tariff_rank(step)))
    if first == "forecast":
        first = "charge_planning"
    return await open_page(hass, entry, first)


def _tariff_rank(step: str) -> int:
    return TARIFF_ORDER.index(step) if step in TARIFF_ORDER else 0


async def options_wizard(hass, entry, steps: dict[str, dict[str, Any]], *, confirm: bool = True):
    """Run Configure for *entry* through the screens in *steps*, then save, and return the result.

    *steps* maps a step id to the values to submit on it (an empty dict accepts the defaults).
    The pages are opened from the menu in menu order, and the tariff screens from the tariff
    menu. A form the flow shows that is not listed fails the test. Save changes is chosen at
    the end when it is offered, and the confirm form is submitted when *confirm* is true.
    """
    if "charge_planning" in steps or "forecast" in steps:
        # The solar forecast screen always follows the charge planning screen.
        steps = {"charge_planning": {}, **steps, **{"forecast": steps.get("forecast", {})}}
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    to_do = list(steps)
    seen: list[str] = []
    while True:
        if len(seen) > MAX_SCREENS:
            return result
        if result["type"] is FlowResultType.MENU:
            chosen = await _next_from_menu(manager, result, to_do)
            if chosen is None:
                # Nothing changed, so there is nothing to save: the menu is the last screen.
                await hass.async_block_till_done()
                return result
            result = chosen
            continue
        if result["type"] is not FlowResultType.FORM:
            await hass.async_block_till_done()
            return result
        step_id = result["step_id"]
        seen.append(step_id)
        if result.get("errors"):
            return result
        if step_id == "confirm":
            if not confirm:
                return result
            result = await manager.async_configure(result["flow_id"], user_input={})
            continue
        assert step_id in steps, f"unexpected step {step_id}, wanted {list(steps)}, saw {seen}"
        if step_id in to_do:
            to_do.remove(step_id)
        result = await submit(manager, result, **steps[step_id])


async def _next_from_menu(manager, result, to_do: list[str]):
    """The next screen for the steps left, Save changes when none is left, or None."""
    options = result["menu_options"]
    if result["step_id"] == "tariff_menu":
        for step in TARIFF_ORDER:
            if step in to_do and step in options:
                if step == "tariff_reviewed":
                    to_do.remove(step)
                return await choose(manager, result, step)
        return await choose(manager, result, "init")
    for page in PAGE_ORDER:
        if any(PAGE_OF_STEP[step] == page for step in to_do):
            return await choose(manager, result, MENU_OPTION_OF_PAGE[page])
    if "confirm" in options:
        return await choose(manager, result, "confirm")
    return None


async def walk_options_forms(hass, entry) -> dict[str, dict]:
    """Every form and menu of Configure, each opened from its menu and submitted untouched.

    Returns the serialised fields and the result by step id, and aborts before the write. A form
    is described as {"fields": [...], "result": result}. A menu has no fields.
    """
    manager = hass.config_entries.options
    forms: dict[str, dict] = {}
    result = await manager.async_init(entry.entry_id)
    forms["init"] = {"fields": [], "result": result}
    result = await choose(manager, result, "tariff_menu")
    forms["tariff_menu"] = {"fields": [], "result": result}
    result = await choose(manager, result, "tariff")
    forms["tariff"] = {"fields": serialised(result), "result": result}
    result = await submit(manager, result, rate_count="1")
    if result["step_id"] != "tariff_rates":
        result = await choose(manager, result, "tariff_rates")
    forms["tariff_rates"] = {"fields": serialised(result), "result": result}
    result = await submit(manager, result, rate_period_1={"rate": 0.1})
    for step in ("bill", "schedule_change"):
        result = await choose(manager, result, step)
        forms[step] = {"fields": serialised(result), "result": result}
        result = await submit(manager, result)
    result = await choose(manager, result, "init")
    for page in ("battery", "charge_planning", "hot_water", "ev"):
        result = await choose(manager, result, page)
        forms[page] = {"fields": serialised(result), "result": result}
        result = await submit(manager, result)
        if page == "charge_planning":
            forms["forecast"] = {"fields": serialised(result), "result": result}
            result = await submit(manager, result)
    result = await choose(manager, result, "confirm")
    forms["confirm"] = {"fields": serialised(result), "result": result}
    manager.async_abort(result["flow_id"])
    return forms


async def to_confirm(manager, result):
    """From the tariff menu or the main menu, open the confirm form of Save changes."""
    if result["step_id"] == "tariff_menu":
        result = await choose(manager, result, "init")
    return await choose(manager, result, "confirm")


async def save_changes(hass, result):
    """From a menu, choose Save changes and submit the confirm form."""
    manager = hass.config_entries.options
    result = await to_confirm(manager, result)
    result = await manager.async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    return result
