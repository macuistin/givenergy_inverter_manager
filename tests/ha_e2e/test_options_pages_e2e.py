"""The pages of the options wizard against a real flow manager: the tariff and its rate rows,
the battery, forecast, hot water and EV pages, and what the forms offer.

The checklist, the routing, last_step and the one write are in test_options_flow_e2e.py.
"""

from __future__ import annotations

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
from custom_components.givenergy_inverter_manager.core.wizard_model import PAGE_KEYS

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


async def test_last_step_is_true_only_on_the_last_tariff_screen_of_a_single_page(
    hass, loaded_entry
):
    result = await open_options(hass, loaded_entry, {"tariff": {}})
    assert result["last_step"] is False
    result = await submit(manager(hass), result, edit_rates=True, edit_bill=True)
    assert result["step_id"] == "tariff_rates"
    assert result["last_step"] is False
    result = await submit(manager(hass), result)
    assert result["step_id"] == "bill"
    assert result["last_step"] is True
    manager(hass).async_abort(result["flow_id"])


async def test_the_tariff_screens_are_not_the_last_when_another_page_follows(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"tariff": {}, "ev": {}})
    result = await submit(manager(hass), result, edit_bill=True)
    assert result["step_id"] == "bill"
    assert result["last_step"] is False
    result = await submit(manager(hass), result)
    assert result["step_id"] == "ev"
    assert result["last_step"] is False
    manager(hass).async_abort(result["flow_id"])


@pytest.fixture
def setups(monkeypatch) -> list[str]:
    """Record every time the integration is set up."""
    import custom_components.givenergy_inverter_manager as integration

    calls: list[str] = []
    real = integration.async_setup_entry

    async def counting(hass, entry):
        calls.append(entry.entry_id)
        return await real(hass, entry)

    monkeypatch.setattr(integration, "async_setup_entry", counting)
    return calls


async def test_a_tariff_change_applies_without_a_reload(hass, loaded_entry, setups):
    coordinator = loaded_entry.runtime_data

    await options_wizard(hass, loaded_entry, {"tariff": {"export_rate": 0.25}})

    assert setups == []
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data is coordinator
    assert coordinator.export_rate == pytest.approx(0.25)


async def test_a_currency_change_reloads_once(hass, loaded_entry, setups):
    await options_wizard(hass, loaded_entry, {"tariff": {}, "bill": {"currency": "GBP"}})

    assert len(setups) == 1
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.data.currency_symbol == "£"


async def test_saving_every_page_unchanged_does_not_reload_or_write(hass, loaded_entry, setups):
    before = dict(loaded_entry.options)

    await options_wizard(
        hass, loaded_entry, {"tariff": {}, "battery": {}, "forecast": {}, "hot_water": {}, "ev": {}}
    )

    assert setups == []
    assert dict(loaded_entry.options) == before
