"""The options wizard against a real flow manager, including the forms the frontend receives.

"What would you like to change?" is a checklist. Only the ticked pages are shown, in a fixed
order, and nothing is written until the last screen. The page logic has its own unit tests
(tests/core/test_wizard_*.py). These prove what only Home Assistant proves: routing, last_step,
the one write, what reloads, and that every form serialises for the frontend.
"""

from __future__ import annotations

import itertools

import pytest
from conftest import FORECAST, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import (
    every_field,
    field_names,
    initial_data,
    open_options,
    options_wizard,
    serialised,
    submit,
    walk_options_forms,
)

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
from custom_components.givenergy_inverter_manager.core.wizard_model import PAGE_KEYS, PAGE_WRITES

OPTIONAL_ENTITY_KEYS = (
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_ENTITY_D2,
    CONF_CARBON_INTENSITY_ENTITY,
)
PAGES = ("tariff", "battery", "forecast", "hot_water", "ev")


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


# ── The checklist ─────────────────────────────────────────────────────────────


async def test_the_checklist_offers_the_five_pages_with_nothing_ticked(hass, loaded_entry):
    result = await manager(hass).async_init(loaded_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["last_step"] is False
    (field,) = serialised(result)
    assert field["name"] == "pages"
    assert field["default"] == []
    assert field["selector"]["select"]["multiple"] is True
    assert field["selector"]["select"]["mode"] == "list"
    assert [o["value"] for o in field["selector"]["select"]["options"]] == list(PAGES)
    manager(hass).async_abort(result["flow_id"])


async def test_each_checklist_line_carries_the_current_status(hass, loaded_entry):
    result = await manager(hass).async_init(loaded_entry.entry_id)

    labels = {o["value"]: o["label"] for o in serialised(result)[0]["selector"]["select"]["options"]}
    assert labels["tariff"] == "Tariff: Day 0.3334 EUR/kWh, export 0.1950, 2 time-of-day rates"
    assert labels["battery"] == "Battery and charging: battery 9.5 kWh, inverter 5 kW"
    assert labels["hot_water"].startswith("Hot water: immersion switch switch.immersion_heater")
    assert labels["ev"] == "EV charger: car efficiency 15 kWh per 100 km"
    manager(hass).async_abort(result["flow_id"])


async def test_ticking_nothing_asks_again_and_writes_nothing(hass, loaded_entry):
    before = dict(loaded_entry.options)
    result = await manager(hass).async_init(loaded_entry.entry_id)

    result = await manager(hass).async_configure(result["flow_id"], user_input={"pages": []})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "nothing_ticked"}
    assert dict(loaded_entry.options) == before
    manager(hass).async_abort(result["flow_id"])


async def test_the_pages_run_in_a_fixed_order_whatever_order_the_client_sends(hass, loaded_entry):
    result = await manager(hass).async_init(loaded_entry.entry_id)
    result = await manager(hass).async_configure(
        result["flow_id"], user_input={"pages": ["ev", "hot_water", "battery"]}
    )
    seen = []
    while result["type"] is FlowResultType.FORM and result["step_id"] != "confirm":
        seen.append(result["step_id"])
        result = await submit(manager(hass), result)

    assert seen == ["battery", "hot_water", "ev"]
    assert result["step_id"] == "confirm"
    manager(hass).async_abort(result["flow_id"])


@pytest.mark.parametrize("page", PAGES)
async def test_a_single_page_shows_only_that_page(hass, loaded_entry, page):
    result = await manager(hass).async_init(loaded_entry.entry_id)
    result = await manager(hass).async_configure(result["flow_id"], user_input={"pages": [page]})

    assert result["step_id"] == page
    assert result["last_step"] is (page != "tariff")
    result = await submit(manager(hass), result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    "ticked",
    [
        combo
        for size in range(1, len(PAGES) + 1)
        for combo in itertools.combinations(PAGES, size)
    ],
    ids=lambda combo: "+".join(combo),
)
async def test_every_combination_of_ticked_pages_walks_to_the_end(hass, loaded_entry, ticked):
    """Each page can be skipped. Whatever is ticked, the wizard ends and the entry stays loaded."""
    result = await manager(hass).async_init(loaded_entry.entry_id)
    result = await manager(hass).async_configure(
        result["flow_id"], user_input={"pages": list(ticked)}
    )
    seen = []
    while result["type"] is FlowResultType.FORM:
        seen.append(result["step_id"])
        result = await submit(manager(hass), result)
    await hass.async_block_till_done()

    assert [s for s in seen if s in PAGES] == [p for p in PAGES if p in ticked]
    assert ("confirm" in seen) is (len(ticked) > 1)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.state is ConfigEntryState.LOADED


# ── last_step and what is written when ────────────────────────────────────────


async def test_last_step_is_false_until_the_confirm_step_of_a_longer_run(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"battery": {}, "ev": {}})
    assert result["step_id"] == "battery"
    assert result["last_step"] is False
    result = await submit(manager(hass), result)
    assert result["step_id"] == "ev"
    assert result["last_step"] is False
    result = await submit(manager(hass), result)
    assert result["step_id"] == "confirm"
    assert result["last_step"] is True
    manager(hass).async_abort(result["flow_id"])


async def test_nothing_is_written_before_the_last_screen(hass, loaded_entry):
    before = dict(loaded_entry.options)
    result = await open_options(hass, loaded_entry, {"battery": {}, "ev": {}})
    result = await submit(manager(hass), result, battery_min_soc_pct=15)
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)
    assert result["step_id"] == "confirm"
    assert dict(loaded_entry.options) == before

    manager(hass).async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert dict(loaded_entry.options) == before


async def test_one_page_that_applies_live_skips_the_confirm_step(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"battery": {}})
    assert result["last_step"] is True

    result = await submit(manager(hass), result, battery_min_soc_pct=15)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["battery_min_soc_pct"] == 15


async def test_one_page_that_reloads_still_asks_to_confirm(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"hot_water": {}})
    result = await submit(manager(hass), result, immersion_switch_entity="switch.second_heater")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    text = result["description_placeholders"]["changes"]
    assert "Immersion switch: switch.immersion_heater to switch.second_heater" in text
    assert "Reloads the integration because you changed immersion switch." in text
    assert "immersion_switch_entity" not in loaded_entry.options
    manager(hass).async_abort(result["flow_id"])


async def test_the_confirm_step_lists_each_change_and_says_it_applies_now(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"battery": {}, "ev": {}})
    result = await submit(manager(hass), result, battery_min_soc_pct=15)
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=19.0)

    text = result["description_placeholders"]["changes"]
    assert "- Battery minimum charge: 10% to 15%" in text
    assert "- Car efficiency: 15 kWh per 100 km to 19 kWh per 100 km" in text
    assert text.endswith("Applies now. The integration does not reload.")
    result = await manager(hass).async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["battery_min_soc_pct"] == 15


async def test_the_confirm_step_of_an_untouched_run_says_nothing_changes(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"battery": {}, "ev": {}})
    result = await submit(manager(hass), result)
    result = await submit(manager(hass), result)

    text = result["description_placeholders"]["changes"]
    assert text == "No values changed.\n\nNothing changes."
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
        "battery": {"battery": {"battery_min_soc_pct": 12}},
        "forecast": {"forecast": {"forecast_entity_p10": "sensor.other_p10"}},
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
        hass, loaded_entry, {"battery": {}, "forecast": {}, "hot_water": {}, "ev": {}}
    )

    assert dict(loaded_entry.options) == before


async def test_a_control_moved_while_a_page_is_open_keeps_its_value(hass, loaded_entry):
    """The options are read when the wizard writes, not when it opened."""
    result = await open_options(hass, loaded_entry, {"battery": {}})
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "dry_run": True, "cheap_rate_floor_soc": 15}
    )

    await submit(manager(hass), result, battery_min_soc_pct=12)
    await hass.async_block_till_done()

    assert loaded_entry.options["battery_min_soc_pct"] == 12
    assert loaded_entry.options["dry_run"] is True
    assert loaded_entry.options["cheap_rate_floor_soc"] == 15


async def test_a_control_moved_between_the_confirm_step_and_its_submit_keeps_its_value(
    hass, loaded_entry
):
    result = await open_options(hass, loaded_entry, {"battery": {}, "ev": {}})
    result = await submit(manager(hass), result, battery_min_soc_pct=12)
    result = await submit(manager(hass), result, car_efficiency_kwh_per_100km=18.0)
    assert result["step_id"] == "confirm"
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "skip_charge_soc_threshold_pct": 90}
    )

    await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()

    assert loaded_entry.options["skip_charge_soc_threshold_pct"] == 90
    assert loaded_entry.options["battery_min_soc_pct"] == 12
    assert loaded_entry.options["car_efficiency_kwh_per_100km"] == 18.0


# ── The tariff and its rate rows ──────────────────────────────────────────────


async def test_the_tariff_screen_states_the_cheapest_rate_and_billing_period(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}})

    summary = result["description_placeholders"]["tariff_summary"]
    assert (
        "Cheapest rate in your saved tariff: Nightboost at 0.0965 EUR/kWh, 02:00 to 04:00."
        in summary
    )
    assert "Your bill runs from the 16th to the 15th." in summary
    manager(hass).async_abort(result["flow_id"])


async def test_the_tariff_screen_follows_saved_options_over_setup_data(hass, loaded_entry):
    hass.config_entries.async_update_entry(
        loaded_entry,
        options={
            "rate_periods": [{"name": "Free", "rate": 0.0, "start": "11:00", "end": "14:00"}],
            "bill_start_day": 1,
        },
    )
    await hass.async_block_till_done()

    result = await open_options(hass, loaded_entry, {"tariff": {}})

    summary = result["description_placeholders"]["tariff_summary"]
    assert "Free at 0.0000 EUR/kWh, 11:00 to 14:00" in summary
    assert "from the 1st to the last day of the month" in summary
    assert initial_data(serialised(result))["rate_count"] == "1"
    manager(hass).async_abort(result["flow_id"])


async def test_a_tariff_change_takes_effect_and_the_rate_rows_are_untouched(hass, loaded_entry):
    result = await options_wizard(hass, loaded_entry, {"tariff": {"export_rate": 0.21}})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["export_rate"] == pytest.approx(0.21)
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.21)
    assert CONF_RATE_PERIODS not in loaded_entry.options
    in_force = loaded_entry.runtime_data._effective_cfg()[CONF_RATE_PERIODS]
    assert [p["name"] for p in in_force] == ["Night", "Nightboost"]
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_the_rates_screen_has_as_many_rows_as_the_count_says(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}, "tariff_rates": {}})
    assert initial_data(serialised(result))["rate_count"] == "2"
    result = await submit(manager(hass), result, rate_count="4", edit_rates=False)

    assert result["step_id"] == "tariff_rates"
    assert field_names(result) == ["rate_period_1", "rate_period_2", "rate_period_3", "rate_period_4"]
    rows = initial_data(serialised(result))
    assert rows["rate_period_1"]["name"] == "Night"
    assert rows["rate_period_2"]["name"] == "Nightboost"
    assert rows["rate_period_3"]["name"] == "Rate 3"
    assert "rate" not in rows["rate_period_3"]
    manager(hass).async_abort(result["flow_id"])


async def test_raising_the_count_opens_the_rows_by_itself_and_saves_the_new_row(
    hass, loaded_entry
):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    result = await submit(manager(hass), result, rate_count="3")
    assert result["step_id"] == "tariff_rates"

    row = {"name": "Evening", "rate": 0.4, "start": "17:00:00", "end": "19:00:00"}
    result = await submit(manager(hass), result, rate_period_3=row)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [p["name"] for p in loaded_entry.options[CONF_RATE_PERIODS]] == [
        "Night",
        "Nightboost",
        "Evening",
    ]
    assert loaded_entry.options[CONF_RATE_PERIODS][2]["start"] == "17:00"


async def test_lowering_the_count_drops_the_last_rows_in_one_screen(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    result = await submit(manager(hass), result, rate_count="1")

    assert result["step_id"] == "tariff_rates"
    assert field_names(result) == ["rate_period_1"]
    result = await submit(manager(hass), result)
    await hass.async_block_till_done()

    assert [p["name"] for p in loaded_entry.options[CONF_RATE_PERIODS]] == ["Night"]


async def test_a_count_of_zero_clears_the_rates_without_a_rates_screen(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    result = await submit(manager(hass), result, rate_count="0")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_RATE_PERIODS] == []
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_the_rates_screen_can_be_opened_with_the_tick_box(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    result = await submit(manager(hass), result, edit_rates=True)

    assert result["step_id"] == "tariff_rates"
    assert len(field_names(result)) == 2
    manager(hass).async_abort(result["flow_id"])


async def test_the_bill_screen_has_the_bill_details_and_saves_them(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}, "bill": {}})
    result = await submit(manager(hass), result, edit_bill=True)
    assert result["step_id"] == "bill"
    assert field_names(result) == [
        "currency",
        "base_rate_name",
        "bill_start_day",
        "standing_charge_per_day",
        "pso_levy_per_month",
        "vat_rate",
        "discount_rate",
    ]
    result = await submit(manager(hass), result, vat_rate=13.5, currency="GBP")
    await hass.async_block_till_done()

    assert result["step_id"] == "confirm"
    assert "- Currency: EUR to GBP" in result["description_placeholders"]["changes"]
    result = await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    assert loaded_entry.options["vat_rate"] == pytest.approx(13.5)
    assert loaded_entry.runtime_data.data.currency_symbol == "£"
    assert loaded_entry.state is ConfigEntryState.LOADED


SLOT_EMPTY = {"name": "Empty", "rate": 0.01, "start": "00:00:00", "end": "00:00:00"}


async def _rates_screen(hass, entry, count: str):
    result = await open_options(hass, entry, {"tariff": {}, "tariff_rates": {}})
    return await submit(manager(hass), result, rate_count=count, edit_rates=True)


async def test_the_rates_screen_rejects_a_zero_length_row_and_keeps_what_was_typed(
    hass, loaded_entry
):
    result = await _rates_screen(hass, loaded_entry, "3")
    result = await submit(manager(hass), result, rate_period_3=SLOT_EMPTY)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tariff_rates"
    assert result["errors"] == {"base": "rate_period_zero_length"}
    assert serialised(result)
    assert CONF_RATE_PERIODS not in loaded_entry.options
    manager(hass).async_abort(result["flow_id"])


async def test_the_rates_screen_rejects_duplicate_names_in_any_case(hass, loaded_entry):
    result = await _rates_screen(hass, loaded_entry, "3")
    row = {"name": "night", "rate": 0.2, "start": "10:00:00", "end": "11:00:00"}
    result = await submit(manager(hass), result, rate_period_3=row)

    assert result["errors"] == {"base": "rate_period_duplicate_name"}
    manager(hass).async_abort(result["flow_id"])


async def test_the_rates_screen_rejects_a_row_named_like_the_base_rate(hass, loaded_entry):
    result = await _rates_screen(hass, loaded_entry, "3")
    row = {"name": "Day", "rate": 0.2, "start": "10:00:00", "end": "11:00:00"}
    result = await submit(manager(hass), result, rate_period_3=row)

    assert result["errors"] == {"base": "rate_period_duplicate_name"}
    manager(hass).async_abort(result["flow_id"])


async def test_the_bill_screen_rejects_a_base_name_that_a_timed_rate_already_uses(
    hass, loaded_entry
):
    result = await open_options(hass, loaded_entry, {"tariff": {}, "bill": {}})
    result = await submit(manager(hass), result, edit_bill=True)
    result = await submit(manager(hass), result, base_rate_name="NIGHT")

    assert result["step_id"] == "bill"
    assert result["errors"] == {"base": "rate_period_duplicate_name"}
    manager(hass).async_abort(result["flow_id"])


async def test_a_zero_base_rate_with_no_timed_rate_is_refused(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    result = await submit(manager(hass), result, base_rate=0.0, rate_count="0")

    assert result["step_id"] == "tariff"
    assert result["errors"] == {"base": "base_rate_required"}
    manager(hass).async_abort(result["flow_id"])


# ── The other pages ───────────────────────────────────────────────────────────


async def test_the_battery_page_has_every_field_with_a_default(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"battery": {}})

    fields = {f["name"]: f for f in serialised(result)}
    assert set(fields) == {
        "battery_capacity_kwh",
        "inverter_max_output_kw",
        "battery_min_soc_pct",
        "overnight_charge_target_pct",
        "battery_cost_eur",
        "battery_throughput_budget_kwh",
    }
    assert all("default" in field for field in fields.values())
    assert fields["overnight_charge_target_pct"]["default"] == 80
    manager(hass).async_abort(result["flow_id"])


async def test_the_battery_page_warns_once_when_the_floor_is_below_the_minimum(
    hass, loaded_entry
):
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, "cheap_rate_floor_soc": 12}
    )
    result = await open_options(hass, loaded_entry, {"battery": {}})

    result = await submit(manager(hass), result, battery_min_soc_pct=20)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "battery"
    assert "Cheap rate floor SoC" in result["description_placeholders"]["warnings"]
    assert "battery_min_soc_pct" not in loaded_entry.options

    result = await submit(manager(hass), result, battery_min_soc_pct=20)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options["battery_min_soc_pct"] == 20


async def test_a_zero_throughput_budget_survives_reopening_the_page(hass, loaded_entry):
    for budget in (4, 0):
        await options_wizard(hass, loaded_entry, {"battery": {"battery_throughput_budget_kwh": budget}})
        assert loaded_entry.options["battery_throughput_budget_kwh"] == budget

    result = await open_options(hass, loaded_entry, {"battery": {}})
    assert initial_data(serialised(result))["battery_throughput_budget_kwh"] == 0
    manager(hass).async_abort(result["flow_id"])


async def test_an_emptied_forecast_and_carbon_selection_is_accepted(hass, loaded_entry):
    """The frontend omits an emptied optional selector."""
    result = await options_wizard(
        hass, loaded_entry, {"forecast": dict.fromkeys(OPTIONAL_ENTITY_KEYS)}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    for key in OPTIONAL_ENTITY_KEYS:
        assert not loaded_entry.runtime_data._effective_cfg().get(key)
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.last_update_success


async def test_the_pages_reopen_after_an_emptied_submission(hass, loaded_entry):
    values = dict.fromkeys(OPTIONAL_ENTITY_KEYS)
    await options_wizard(hass, loaded_entry, {"forecast": values, "hot_water": {}})

    forms = await walk_options_forms(hass, loaded_entry)

    assert set(forms) >= {"init", "tariff", "battery", "forecast", "hot_water", "ev", "confirm"}
    for step_id, form in forms.items():
        assert form["fields"] or step_id == "confirm"


async def test_a_cleared_forecast_stays_cleared_when_the_page_reopens(hass, loaded_entry):
    await options_wizard(hass, loaded_entry, {"forecast": {CONF_FORECAST_ENTITY: FORECAST}})
    assert loaded_entry.runtime_data._effective_cfg()[CONF_FORECAST_ENTITY] == FORECAST

    await options_wizard(hass, loaded_entry, {"forecast": {CONF_FORECAST_ENTITY: None}})
    assert not loaded_entry.runtime_data._effective_cfg().get(CONF_FORECAST_ENTITY)

    result = await open_options(hass, loaded_entry, {"forecast": {}})
    suggested = {
        f["name"]: (f.get("description") or {}).get("suggested_value") for f in serialised(result)
    }
    assert not suggested[CONF_FORECAST_ENTITY]
    manager(hass).async_abort(result["flow_id"])


async def test_the_forecast_page_says_what_was_found_and_what_the_sensors_read(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"forecast": {}})

    placeholders = result["description_placeholders"]
    assert placeholders["detected"] == "Found Forecast.Solar: sensor.energy_production_tomorrow."
    if loaded_entry.data.get(CONF_FORECAST_ENTITY):
        assert "sensor.energy_production_tomorrow reads 14.2 kWh." in placeholders["check"]
    else:
        assert placeholders["check"] == "No sensor is set yet."
    manager(hass).async_abort(result["flow_id"])


async def test_the_hot_water_page_lists_immersion_switches_without_choosing_one(hass, loaded_entry):
    hass.states.async_set("switch.immersion_spare", "off")
    result = await open_options(hass, loaded_entry, {"hot_water": {}})

    candidates = result["description_placeholders"]["candidates"]
    assert "switch.immersion_heater" in candidates
    assert "switch.immersion_spare" in candidates
    chosen = initial_data(serialised(result))["immersion_switch_entity"]
    assert chosen == "switch.immersion_heater"
    manager(hass).async_abort(result["flow_id"])


async def test_a_hot_water_warning_is_shown_once_and_never_blocks_saving(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"hot_water": {}})
    values = {"immersion_ready_times": ["07:00"], "immersion_temp_sensor_entity": None}

    result = await submit(manager(hass), result, **values)
    assert result["step_id"] == "hot_water"
    assert not result.get("errors")
    assert "temperature sensor" in result["description_placeholders"]["warnings"]

    result = await submit(manager(hass), result, **values)
    assert result["step_id"] == "confirm"  # clearing the sensor changes the device set
    assert "temperature sensor" in result["description_placeholders"]["warnings"]
    await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    assert loaded_entry.options["immersion_ready_times"] == ["07:00"]


async def test_no_page_asks_for_a_control_or_a_retired_setting(hass, loaded_entry):
    forms = await walk_options_forms(hass, loaded_entry)

    names = {f["name"] for form in forms.values() for f in every_field(form["fields"])}
    assert names.isdisjoint(
        {
            "dry_run",
            "verbose_logging",
            "surplus_divert_soc_pct",
            "surplus_divert_min_power_w",
            "cheap_rate_floor_soc",
            "skip_charge_soc_threshold_pct",
            "forecast_conservatism",
            "immersion_target_temp_c",
            "immersion_min_temp_c",
            "immersion_hysteresis_c",
            "forecast_provider",
            "discovered_charger",
        }
    )


async def test_no_entity_or_select_field_defaults_to_an_empty_string(hass, loaded_entry):
    """An empty string default fails entity and select validation when a form is submitted."""
    forms = await walk_options_forms(hass, loaded_entry)

    empty = [
        f["name"]
        for form in forms.values()
        for f in every_field(form["fields"])
        if f.get("default") == "" and set(f["selector"]) & {"entity", "select"}
    ]
    assert empty == []


async def test_every_page_keeps_its_keys_in_the_page_table(hass, loaded_entry):
    """A form field that is stored is a key some page owns."""
    forms = await walk_options_forms(hass, loaded_entry)
    stored = {key for keys in PAGE_KEYS.values() for key in keys}
    form_only = {
        "pages",
        "rate_count",
        "edit_rates",
        "edit_bill",
        "schedule_change",
        "confirm_current",
        "effective_from",
        "cancel_scheduled",
        "name",
        "rate",
        "start",
        "end",
    }

    names = {f["name"] for form in forms.values() for f in every_field(form["fields"])}

    assert names - form_only <= stored
