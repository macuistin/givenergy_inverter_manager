"""Configure against a real flow manager, including the forms the frontend receives.

Configure is a menu of pages. Each page comes back to the menu, Save changes shows once
something has changed, and nothing is written until the changes are saved. The page logic has its own unit tests
(tests/core/test_wizard_*.py). These prove what only Home Assistant proves: routing, last_step,
the one write, what reloads, and that every form serialises for the frontend.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import (
    choose,
    open_options,
    open_page,
    options_wizard,
    submit,
)

from custom_components.givenergy_inverter_manager.const import (
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_FORECAST_CONSERVATISM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_PROVIDER,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.wizard_model import PAGE_WRITES

OPTIONAL_ENTITY_KEYS = (
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_ENTITY_D2,
    CONF_CARBON_INTENSITY_ENTITY,
)
PAGES = ("tariff", "battery", "charge_planning", "hot_water", "ev")


@pytest.fixture
def scenario():
    """These tests do not depend on the time of day."""
    return MIDDAY


@pytest.fixture(params=[True, False], ids=["forecast_configured", "no_forecast_configured"])
def config_entry(request):
    """Entry with, or without, forecast and carbon entities in its stored data."""
    data = full_config_data()
    if not request.param:
        for key in (*OPTIONAL_ENTITY_KEYS, CONF_FORECAST_PROVIDER, CONF_FORECAST_CONSERVATISM):
            data.pop(key)
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )


def manager(hass):
    return hass.config_entries.options


MENU = ["tariff_menu", "battery", "charge_planning", "hot_water", "ev"]


async def save(hass, result):
    """Choose Save changes on the menu *result*, then submit the confirm form."""
    result = await choose(manager(hass), result, "confirm")
    assert result["step_id"] == "confirm"
    return await manager(hass).async_configure(result["flow_id"], user_input={})


# ── The menu ──────────────────────────────────────────────────────────────────


async def test_the_menu_offers_the_five_pages_and_no_save_before_a_change(hass, loaded_entry):
    result = await manager(hass).async_init(loaded_entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == MENU
    assert result["description_placeholders"]["unsaved"] == ""
    manager(hass).async_abort(result["flow_id"])


async def test_each_menu_line_carries_the_current_status(hass, loaded_entry):
    result = await manager(hass).async_init(loaded_entry.entry_id)

    lines = result["description_placeholders"]
    assert lines["tariff_summary_line"] == "Day 0.3334 EUR/kWh, export 0.1950, 2 time-of-day rates"
    assert lines["battery_summary"] == "battery 9.5 kWh, inverter 5 kW"
    assert lines["charge_planning_summary"].startswith(
        "minimum charge 10%, overnight cap 80%, forecast"
    )
    assert lines["hot_water_summary"].startswith("immersion switch switch.immersion_heater")
    assert lines["ev_summary"] == "car efficiency 15 kWh per 100 km"
    manager(hass).async_abort(result["flow_id"])


@pytest.mark.parametrize("page", ["battery", "charge_planning", "hot_water", "ev"])
async def test_each_page_returns_to_the_menu(hass, loaded_entry, page):
    """A page submitted unchanged comes back to the menu, which still offers no save."""
    result = await open_page(hass, loaded_entry, page)
    assert result["last_step"] is False
    result = await submit(manager(hass), result)
    if page == "charge_planning":
        assert result["step_id"] == "forecast"  # the second screen of charge planning
        result = await submit(manager(hass), result)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert "confirm" not in result["menu_options"]
    manager(hass).async_abort(result["flow_id"])


async def test_a_change_adds_save_changes_and_lists_it_above_the_menu(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "ev")
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)

    assert result["menu_options"] == [*MENU, "confirm"]
    unsaved = result["description_placeholders"]["unsaved"]
    assert "Car efficiency: 15 kWh per 100 km to 19 kWh per 100 km" in unsaved
    assert result["description_placeholders"]["save_note"] == "Applies at once."
    manager(hass).async_abort(result["flow_id"])


async def test_save_changes_says_when_it_reloads(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "hot_water")
    result = await submit(manager(hass), result, immersion_switch_entity="switch.second_heater")

    note = result["description_placeholders"]["save_note"]
    assert note == "Reloads the integration, so entities are unavailable for a few seconds."
    manager(hass).async_abort(result["flow_id"])


async def test_several_pages_are_saved_in_one_write(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "charge_planning")
    result = await submit(manager(hass), result, battery_min_soc_pct=15)
    result = await submit(manager(hass), result)
    result = await choose(manager(hass), result, "ev")
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)

    result = await save(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["battery_min_soc_pct"] == 15
    assert loaded_entry.options["car_efficiency_kwh_per_100km"] == 19.0
    assert loaded_entry.state is ConfigEntryState.LOADED


# ── last_step and what is written when ────────────────────────────────────────


async def test_last_step_is_true_only_on_the_confirm_form(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "battery")
    assert result["last_step"] is False
    result = await submit(manager(hass), result, battery_capacity_kwh=12.0)
    result = await choose(manager(hass), result, "confirm")
    assert result["step_id"] == "confirm"
    assert result["last_step"] is True
    manager(hass).async_abort(result["flow_id"])


async def test_nothing_is_written_before_save_changes(hass, loaded_entry):
    before = dict(loaded_entry.options)
    result = await open_page(hass, loaded_entry, "charge_planning")
    result = await submit(manager(hass), result, battery_min_soc_pct=15)
    result = await submit(manager(hass), result)
    result = await choose(manager(hass), result, "ev")
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)
    assert result["step_id"] == "init"
    assert dict(loaded_entry.options) == before

    manager(hass).async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert dict(loaded_entry.options) == before


async def test_the_confirm_step_lists_each_change_and_says_it_applies_now(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "charge_planning")
    result = await submit(manager(hass), result, battery_min_soc_pct=15)
    result = await submit(manager(hass), result)
    result = await choose(manager(hass), result, "ev")
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)
    result = await choose(manager(hass), result, "confirm")

    text = result["description_placeholders"]["changes"]
    assert "- Battery minimum charge: 10% to 15%" in text
    assert "- Car efficiency: 15 kWh per 100 km to 19 kWh per 100 km" in text
    assert text.endswith("Applies now. The integration does not reload.")
    result = await manager(hass).async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["battery_min_soc_pct"] == 15


async def test_the_confirm_step_says_when_it_reloads(hass, loaded_entry):
    result = await open_page(hass, loaded_entry, "hot_water")
    result = await submit(manager(hass), result, immersion_switch_entity="switch.second_heater")
    result = await choose(manager(hass), result, "confirm")

    text = result["description_placeholders"]["changes"]
    assert "Immersion switch: switch.immersion_heater to switch.second_heater" in text
    assert "Reloads the integration because you changed immersion switch." in text
    assert "immersion_switch_entity" not in loaded_entry.options
    manager(hass).async_abort(result["flow_id"])


# ── One write, read at the end ────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES)
async def test_a_page_writes_only_its_own_keys(hass, loaded_entry, page):
    """Page isolation: every other page's saved values are left exactly as they were."""
    saved = {
        "export_rate": 0.25,
        "base_rate_name": "Standard",
        "battery_min_soc_pct": 14,
        "forecast_entity_p10": "sensor.p10",
        "immersion_wattage_w": 2500.0,
        "alt_heat_label": "Gas",
        "car_efficiency_kwh_per_100km": 16.0,
        "tariff_reviewed_on": "2026-06-01",
    }
    hass.config_entries.async_update_entry(loaded_entry, options=dict(saved))
    await hass.async_block_till_done()
    changes = {
        "tariff": {"tariff": {"export_rate": 0.31}},
        "battery": {"battery": {"battery_capacity_kwh": 12.0}},
        "charge_planning": {
            "charge_planning": {"battery_min_soc_pct": 12},
            "forecast": {"forecast_entity_p10": "sensor.other_p10"},
        },
        "hot_water": {"hot_water": {"immersion_wattage_w": 2800}},
        "ev": {"ev": {"car_efficiency_kwh_per_100km": 17.5}},
    }[page]

    result = await options_wizard(hass, loaded_entry, changes)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = dict(loaded_entry.options)
    moved = {k for k in options if options[k] != saved.get(k)}
    assert moved
    assert moved <= PAGE_WRITES[page]
    others = set(saved) - PAGE_WRITES[page]
    assert {k: options[k] for k in others} == {k: saved[k] for k in others}


async def test_a_value_equal_to_what_is_in_force_is_never_written(hass, loaded_entry):
    before = dict(loaded_entry.options)

    await options_wizard(
        hass, loaded_entry, {"battery": {}, "charge_planning": {}, "hot_water": {}, "ev": {}}
    )

    assert dict(loaded_entry.options) == before


async def test_a_control_moved_while_a_page_is_open_keeps_its_value(hass, loaded_entry):
    """The options are read when Configure writes, not when it opened."""
    result = await open_options(hass, loaded_entry, {"charge_planning": {}})
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "dry_run": True, "cheap_rate_floor_soc": 15}
    )

    result = await submit(manager(hass), result, battery_min_soc_pct=12)
    result = await submit(manager(hass), result)
    await save(hass, result)
    await hass.async_block_till_done()

    assert loaded_entry.options["battery_min_soc_pct"] == 12
    assert loaded_entry.options["dry_run"] is True
    assert loaded_entry.options["cheap_rate_floor_soc"] == 15


async def test_a_control_moved_between_the_confirm_step_and_its_submit_keeps_its_value(
    hass, loaded_entry
):
    result = await open_options(hass, loaded_entry, {"charge_planning": {}, "ev": {}})
    result = await submit(manager(hass), result, battery_min_soc_pct=12)
    result = await submit(manager(hass), result)
    result = await choose(manager(hass), result, "ev")
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=18.0)
    result = await choose(manager(hass), result, "confirm")
    assert result["step_id"] == "confirm"
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "skip_charge_soc_threshold_pct": 90}
    )

    await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()

    assert loaded_entry.options["skip_charge_soc_threshold_pct"] == 90
    assert loaded_entry.options["battery_min_soc_pct"] == 12
    assert loaded_entry.options["car_efficiency_kwh_per_100km"] == 18.0
