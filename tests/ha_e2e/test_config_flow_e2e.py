"""The setup wizard against a real flow manager, with and without discovered GivTCP inverters.

The first screen shows what was found and a checklist of what to set up. Only the ticked pages
follow, always in the same order, and nothing is stored until the confirm step creates the entry.
"""

from __future__ import annotations

import itertools

import pytest
from conftest import (
    BATTERY_POWER,
    CAPACITY,
    FORECAST,
    GRID,
    INV_TEMP,
    LOAD,
    MIDDAY,
    SERIAL,
    SOC,
    SOLAR,
    ZAPPI_STATES,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from wizard_support import every_field, field_names, initial_data, serialised, submit

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    DOMAIN,
)

FIVE = {
    CONF_SOLAR_POWER: SOLAR,
    CONF_BATTERY_SOC: SOC,
    CONF_BATTERY_POWER: BATTERY_POWER,
    CONF_GRID_POWER: GRID,
    CONF_HOUSE_LOAD: LOAD,
}
TARIFF = {"base_rate": 0.3, "export_rate": 0.1}
ROWS = {
    "rate_period_1": {"rate": 0.12},
    "rate_period_2": {"rate": 0.2},
}
SECOND_SERIAL = "cd5678h901"


@pytest.fixture
def scenario():
    return MIDDAY


def manager(hass):
    return hass.config_entries.flow


async def start(hass):
    return await manager(hass).async_init(DOMAIN, context={"source": SOURCE_USER})


def only_inverter_states(hass, keep_forecast: bool = False) -> None:
    """Leave only the five power sensors, so nothing is discovered."""
    keep = set(FIVE.values()) | ({FORECAST} if keep_forecast else set())
    for entity_id in list(hass.states.async_entity_ids()):
        if entity_id not in keep:
            hass.states.async_remove(entity_id)


def remove_forecast(hass) -> None:
    hass.states.async_remove(FORECAST)


def add_second_inverter(hass, complete: bool = True) -> None:
    prefix = f"givtcp_{SECOND_SERIAL}"
    hass.states.async_set(f"sensor.{prefix}_invertor_serial_number", SECOND_SERIAL)
    hass.states.async_set(f"sensor.{prefix}_pv_power", 100)
    hass.states.async_set(f"sensor.{prefix}_soc", 50)
    hass.states.async_set(f"sensor.{prefix}_battery_power", 0)
    hass.states.async_set(f"sensor.{prefix}_grid_power", 0)
    if complete:
        hass.states.async_set(f"sensor.{prefix}_load_power", 300)
        hass.states.async_set(f"sensor.{prefix}_battery_capacity_kwh", 13.5)


async def finish(hass, result):
    """Submit the confirm form and unload the entry that was created."""
    assert result["step_id"] == "confirm"
    result = await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return result["result"]


async def unload(hass, entry) -> None:
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def run_pages(hass, result, ticked, **inputs):
    """Submit the system form with *ticked*, then every page with its defaults and *inputs*.

    Returns the screens shown in order and the confirm result.
    """
    shown = [result["step_id"]]
    result = await submit(manager(hass), result, pages=ticked, **inputs.get("system", {}))
    while result["type"] is FlowResultType.FORM and result["step_id"] != "confirm":
        shown.append(result["step_id"])
        values = dict(inputs.get(result["step_id"], {}))
        result = await submit(manager(hass), result, **values)
    shown.append(result["step_id"])
    return shown, result


# ── The first screen ──────────────────────────────────────────────────────────


async def test_the_first_screen_lists_what_was_found_and_the_checklist(
    hass, hass_in_scenario, service_calls
):
    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    remove_forecast(hass)
    result = await start(hass)

    assert result["step_id"] == "system"
    assert result["last_step"] is False
    found = result["description_placeholders"]["found"]
    assert "Inverter: GivTCP ab1234g567, all sensors found and used." in found
    assert "EV charger:" in found
    assert "found and used" in found
    assert "Solar forecast: none found." in found
    fields = {f["name"]: f for f in serialised(result)}
    assert set(fields) == {"inverter_max_output_kw", "pages"}
    assert fields["pages"]["default"] == ["tariff"]
    assert fields["pages"]["selector"]["select"]["options"] == ["tariff", "forecast", "hot_water"]
    assert fields["pages"]["selector"]["select"]["multiple"] is True
    manager(hass).async_abort(result["flow_id"])


async def test_a_forecast_sensor_that_was_found_is_used_and_not_offered(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)

    assert "Forecast.Solar (sensor.energy_production_tomorrow), found and used." in (
        result["description_placeholders"]["found"]
    )
    pages = next(f for f in serialised(result) if f["name"] == "pages")
    assert pages["selector"]["select"]["options"] == ["tariff", "hot_water"]
    shown, confirm = await run_pages(hass, result, ["tariff"], tariff=TARIFF)
    entry = await finish(hass, confirm)
    try:
        assert entry.data["forecast_entity"] == FORECAST
    finally:
        await unload(hass, entry)


async def test_a_found_ev_charger_needs_no_screen(hass, hass_in_scenario, service_calls):
    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    result = await start(hass)

    shown, confirm = await run_pages(hass, result, [], )
    assert shown == ["system", "confirm"]
    assert "EV charger: " in confirm["description_placeholders"]["summary"]
    entry = await finish(hass, confirm)
    try:
        assert "discovered_charger" not in entry.data
    finally:
        await unload(hass, entry)


async def test_the_battery_capacity_field_appears_only_when_givtcp_did_not_report_it(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)
    assert "battery_capacity_kwh" not in field_names(result)
    manager(hass).async_abort(result["flow_id"])

    hass.states.async_set(CAPACITY, "unavailable")
    result = await start(hass)
    assert "battery_capacity_kwh" in field_names(result)
    assert initial_data(serialised(result))["battery_capacity_kwh"] == 10.0
    manager(hass).async_abort(result["flow_id"])


async def test_the_reported_battery_capacity_is_stored(hass, hass_in_scenario, service_calls):
    hass.states.async_set(CAPACITY, 13.5, {"unit_of_measurement": "kWh"})
    result = await start(hass)
    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.data[CONF_BATTERY_CAPACITY] == 13.5
        assert entry.data["inverter_max_output_kw"] == 5.0
    finally:
        await unload(hass, entry)


# ── How many screens ──────────────────────────────────────────────────────────


async def test_a_flat_rate_home_needs_three_screens(hass, hass_in_scenario, service_calls):
    result = await start(hass)
    assert result["description_placeholders"]["progress"] == "Step 1 of about 3."

    shown, confirm = await run_pages(hass, result, ["tariff"], tariff=TARIFF)

    assert shown == ["system", "tariff", "confirm"]
    entry = await finish(hass, confirm)
    await unload(hass, entry)


async def test_day_and_night_rates_need_four_screens(hass, hass_in_scenario, service_calls):
    result = await start(hass)

    shown, confirm = await run_pages(
        hass,
        result,
        ["tariff"],
        tariff={**TARIFF, "rate_count": "2"},
        tariff_rates=ROWS,
    )

    assert shown == ["system", "tariff", "tariff_rates", "confirm"]
    entry = await finish(hass, confirm)
    try:
        assert [p["name"] for p in entry.data["rate_periods"]] == ["Night", "Peak"]
    finally:
        await unload(hass, entry)


async def test_day_night_and_an_immersion_need_five_screens(hass, hass_in_scenario, service_calls):
    result = await start(hass)

    shown, confirm = await run_pages(
        hass,
        result,
        ["tariff", "hot_water"],
        tariff={**TARIFF, "rate_count": "2"},
        tariff_rates=ROWS,
    )

    assert shown == ["system", "tariff", "tariff_rates", "hot_water", "confirm"]
    entry = await finish(hass, confirm)
    await unload(hass, entry)


async def test_skipping_the_tariff_needs_two_screens(hass, hass_in_scenario, service_calls):
    result = await start(hass)

    shown, confirm = await run_pages(hass, result, [])

    assert shown == ["system", "confirm"]
    summary = confirm["description_placeholders"]["summary"]
    assert "Tariff: not set yet." in summary
    entry = await finish(hass, confirm)
    try:
        assert "base_rate" not in entry.data
        assert entry.data["rate_periods"] == []
        assert entry.state is ConfigEntryState.LOADED
    finally:
        await unload(hass, entry)


async def test_the_step_count_is_recomputed_after_each_screen(hass, hass_in_scenario, service_calls):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff", "hot_water"])
    assert result["description_placeholders"]["progress"] == "Step 2 of about 4."
    result = await submit(manager(hass), result, **TARIFF, rate_count="3")
    assert result["step_id"] == "tariff_rates"
    assert result["description_placeholders"]["progress"] == "Step 3 of about 5."
    manager(hass).async_abort(result["flow_id"])


# ── Routing, order and last_step ──────────────────────────────────────────────

PAGE_SETS = [
    combo for size in range(4) for combo in itertools.combinations(["tariff", "forecast", "hot_water"], size)
]


@pytest.mark.parametrize("forecast_found", [True, False], ids=["forecast_found", "no_forecast"])
@pytest.mark.parametrize("ticked", PAGE_SETS, ids=lambda c: "+".join(c) or "none")
async def test_every_combination_of_ticked_pages_creates_a_working_entry(
    hass, hass_in_scenario, service_calls, ticked, forecast_found
):
    """Each page can be skipped. Whatever is ticked, only those pages show, in the same order."""
    if not forecast_found:
        remove_forecast(hass)
    offered = [p for p in ticked if p != "forecast" or not forecast_found]
    result = await start(hass)

    shown, confirm = await run_pages(
        hass, result, list(reversed(offered)), tariff=TARIFF
    )

    assert shown == ["system", *offered, "confirm"]
    entry = await finish(hass, confirm)
    try:
        assert entry.state is ConfigEntryState.LOADED
        assert entry.data["dry_run"] is True
        assert ("base_rate" in entry.data) is ("tariff" in offered)
    finally:
        await unload(hass, entry)


async def test_last_step_is_false_on_every_form_but_the_confirm_step(
    hass, hass_in_scenario, service_calls
):
    remove_forecast(hass)
    result = await start(hass)
    flags = [result["last_step"]]
    result = await submit(manager(hass), result, pages=["tariff", "forecast", "hot_water"])
    while result["step_id"] != "confirm":
        flags.append(result["last_step"])
        values = TARIFF if result["step_id"] == "tariff" else {}
        result = await submit(manager(hass), result, **values)

    assert flags == [False, False, False, False]
    assert result["last_step"] is True
    manager(hass).async_abort(result["flow_id"])


async def test_nothing_is_stored_until_the_confirm_step(hass, hass_in_scenario, service_calls):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff", "hot_water"])
    result = await submit(manager(hass), result, **TARIFF)
    result = await submit(manager(hass), result)
    assert result["step_id"] == "confirm"
    assert not hass.config_entries.async_entries(DOMAIN)

    manager(hass).async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(DOMAIN)


# ── Detect first, ask second ──────────────────────────────────────────────────


async def test_the_currency_comes_from_home_assistant(hass, hass_in_scenario, service_calls):
    hass.config.currency = "GBP"
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])

    bill = next(f for f in serialised(result) if f["name"] == "bill_details")
    defaults = {f["name"]: f.get("default") for f in bill["schema"]}
    assert defaults["currency"] == "GBP"
    result = await submit(manager(hass), result, **TARIFF)
    entry = await finish(hass, result)
    try:
        assert entry.data["currency"] == "GBP"
        assert entry.runtime_data.data.currency_symbol == "£"
    finally:
        await unload(hass, entry)


async def test_an_unknown_home_currency_falls_back_to_the_default(
    hass, hass_in_scenario, service_calls
):
    hass.config.currency = "XTS"
    result = await start(hass)
    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.data["currency"] == "EUR"
    finally:
        await unload(hass, entry)


@pytest.mark.parametrize(
    ("country", "start_time", "end_time"),
    [("IE", "23:00:00", "08:00:00"), ("GB", "00:30:00", "07:30:00"), (None, "23:00:00", "07:00:00")],
)
async def test_the_first_rate_row_starts_from_the_country_night_window(
    hass, hass_in_scenario, service_calls, country, start_time, end_time
):
    hass.config.country = country
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])
    result = await submit(manager(hass), result, **TARIFF, rate_count="1")

    row = initial_data(serialised(result))["rate_period_1"]
    assert (row["name"], row["start"], row["end"]) == ("Night", start_time, end_time)
    assert "rate" not in row
    manager(hass).async_abort(result["flow_id"])


async def test_the_tariff_screen_has_no_placeholder_prices(hass, hass_in_scenario, service_calls):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])

    defaults = initial_data(serialised(result))
    assert "base_rate" not in defaults
    assert "export_rate" not in defaults
    assert defaults["rate_count"] == "0"
    bill = defaults["bill_details"]
    assert (bill["standing_charge_per_day"], bill["pso_levy_per_month"]) == (0.0, 0.0)
    assert (bill["vat_rate"], bill["discount_rate"], bill["bill_start_day"]) == (0.0, 0.0, 1)
    manager(hass).async_abort(result["flow_id"])


async def test_immersion_switch_candidates_are_listed_and_never_applied(
    hass, hass_in_scenario, service_calls
):
    hass.states.async_set("switch.immersion_heater", "off")
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["hot_water"])

    assert "switch.immersion_heater" in result["description_placeholders"]["candidates"]
    assert "immersion_switch_entity" not in initial_data(serialised(result))
    manager(hass).async_abort(result["flow_id"])
    shown, confirm = await run_pages(hass, await start(hass), ["hot_water"])
    entry = await finish(hass, confirm)
    try:
        assert "immersion_switch_entity" not in entry.data
    finally:
        await unload(hass, entry)


async def test_the_entry_has_only_stored_keys_and_no_control_values(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)
    _, confirm = await run_pages(
        hass, result, ["tariff", "hot_water"], tariff=TARIFF
    )
    entry = await finish(hass, confirm)
    try:
        for key in (
            "surplus_divert_soc_pct",
            "surplus_divert_min_power_w",
            "cheap_rate_floor_soc",
            "skip_charge_soc_threshold_pct",
            "forecast_conservatism",
            "verbose_logging",
            "immersion_target_temp_c",
            "immersion_min_temp_c",
            "forecast_provider",
            "discovered_charger",
        ):
            assert key not in entry.data, key
        assert entry.data["dry_run"] is True
    finally:
        await unload(hass, entry)


# ── The inverter ──────────────────────────────────────────────────────────────


async def test_a_discovered_inverter_sets_the_unique_id_and_a_second_flow_is_refused(
    hass, hass_in_scenario, service_calls
):
    flow = manager(hass)
    result = await start(hass)
    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.unique_id == SERIAL
        assert entry.data[CONF_SOLAR_POWER] == SOLAR
        assert entry.data[CONF_INVERTER_TEMP_ENTITY] == INV_TEMP
        assert entry.data[CONF_INVERTER_SERIAL] == SERIAL
        assert entry.state is ConfigEntryState.LOADED
    finally:
        await unload(hass, entry)

    again = await start(hass)
    again = await submit(flow, again, pages=[])
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"


async def test_several_inverters_are_offered_and_the_chosen_one_is_used(
    hass, hass_in_scenario, service_calls
):
    add_second_inverter(hass)
    result = await start(hass)
    fields = {f["name"]: f for f in serialised(result)}
    select = fields["discovered_inverter"]["selector"]["select"]["options"]
    assert [o["value"] for o in select] == [SERIAL, SECOND_SERIAL]
    assert fields["discovered_inverter"]["default"] == SERIAL

    _, confirm = await run_pages(
        hass, result, [], system={"discovered_inverter": SECOND_SERIAL}
    )
    entry = await finish(hass, confirm)
    try:
        assert entry.unique_id == SECOND_SERIAL
        assert entry.data[CONF_SOLAR_POWER] == f"sensor.givtcp_{SECOND_SERIAL}_pv_power"
        assert entry.data[CONF_BATTERY_CAPACITY] == 13.5
    finally:
        await unload(hass, entry)


async def test_an_inverter_with_sensors_missing_sends_the_user_to_the_entity_screen(
    hass, hass_in_scenario, service_calls
):
    for entity_id in list(hass.states.async_entity_ids()):
        if "givtcp" in entity_id:
            hass.states.async_remove(entity_id)
    add_second_inverter(hass, complete=False)
    result = await start(hass)
    assert "some sensors are missing" in result["description_placeholders"]["found"]

    result = await submit(manager(hass), result, pages=[])

    assert result["step_id"] == "inverter_entities"
    assert result["last_step"] is False
    suggested = {
        f["name"]: (f.get("description") or {}).get("suggested_value") for f in serialised(result)
    }
    assert suggested[CONF_SOLAR_POWER] == f"sensor.givtcp_{SECOND_SERIAL}_pv_power"
    assert suggested[CONF_HOUSE_LOAD] is None
    manager(hass).async_abort(result["flow_id"])


async def test_without_any_inverter_the_five_entities_are_chosen_by_hand(
    hass, hass_in_scenario, service_calls
):
    only_inverter_states(hass)
    result = await start(hass)
    assert result["step_id"] == "system"
    assert "No GivTCP inverter was found" in result["description_placeholders"]["found"]
    assert "battery_capacity_kwh" in field_names(result)

    result = await submit(manager(hass), result, pages=[], battery_capacity_kwh=9.5)
    assert result["step_id"] == "inverter_entities"
    required = {f["name"] for f in serialised(result) if f["required"]}
    assert required == set(FIVE)

    result = await submit(manager(hass), result, **FIVE)
    entry = await finish(hass, result)
    try:
        assert entry.unique_id == "manual"
        assert entry.data[CONF_INVERTER_SERIAL] == "manual"
        assert entry.data[CONF_BATTERY_CAPACITY] == 9.5
        assert entry.state is ConfigEntryState.LOADED
    finally:
        await unload(hass, entry)


async def test_the_entity_screen_refuses_a_missing_entity(hass, hass_in_scenario, service_calls):
    from custom_components.givenergy_inverter_manager.core.wizard_pages import missing_wiring

    only_inverter_states(hass)
    result = await start(hass)
    result = await submit(manager(hass), result, pages=[])
    assert missing_wiring({**FIVE, CONF_GRID_POWER: ""}) == {"base": "missing_entities"}
    manager(hass).async_abort(result["flow_id"])


# ── Rate rows, bill details and the confirm text ──────────────────────────────


async def test_the_rates_screen_rejects_a_zero_length_row(hass, hass_in_scenario, service_calls):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])
    result = await submit(manager(hass), result, **TARIFF, rate_count="1")

    slot = {"name": "Empty", "rate": 0.01, "start": "00:00:00", "end": "00:00:00"}
    bad = await submit(manager(hass), result, rate_period_1=slot)
    assert bad["type"] is FlowResultType.FORM
    assert bad["step_id"] == "tariff_rates"
    assert bad["errors"] == {"base": "rate_period_zero_length"}

    slot = {"name": "Evening", "rate": 0.4, "start": "17:00:00", "end": "19:00:00"}
    good = await submit(manager(hass), bad, rate_period_1=slot)
    assert good["step_id"] == "confirm"
    manager(hass).async_abort(good["flow_id"])


async def test_the_rates_screen_rejects_duplicate_names_and_the_base_name(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])
    result = await submit(manager(hass), result, **TARIFF, rate_count="2")

    night = {"name": "Night", "rate": 0.18, "start": "23:00:00", "end": "08:00:00"}
    again = {"name": "NIGHT", "rate": 0.2, "start": "10:00:00", "end": "11:00:00"}
    bad = await submit(manager(hass), result, rate_period_1=night, rate_period_2=again)
    assert bad["errors"] == {"base": "rate_period_duplicate_name"}

    named_like_base = {**again, "name": "Day"}
    bad = await submit(manager(hass), bad, rate_period_2=named_like_base)
    assert bad["errors"] == {"base": "rate_period_duplicate_name"}
    manager(hass).async_abort(bad["flow_id"])


async def test_a_zero_base_rate_is_refused_when_no_timed_rate_covers_the_day(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)
    result = await submit(manager(hass), result, pages=["tariff"])

    result = await submit(manager(hass), result, base_rate=0.0, export_rate=0.1)

    assert result["step_id"] == "tariff"
    assert result["errors"] == {"base": "base_rate_required"}
    manager(hass).async_abort(result["flow_id"])


async def test_the_confirm_step_summarises_the_wizard_before_creating_the_entry(
    hass, hass_in_scenario, service_calls
):
    result = await start(hass)
    tariff = {
        "base_rate": 0.3,
        "export_rate": 0.1,
        "rate_count": "2",
        "bill_details": {"bill_start_day": 16},
    }
    rows = {
        "rate_period_1": {"name": "Night", "rate": 0.12, "start": "23:00:00", "end": "08:00:00"},
        "rate_period_2": {"name": "Boost", "rate": 0.08, "start": "02:00:00", "end": "04:00:00"},
    }
    _, confirm = await run_pages(hass, result, ["tariff"], tariff=tariff, tariff_rates=rows)

    assert not hass.config_entries.async_entries(DOMAIN)
    summary = confirm["description_placeholders"]["summary"]
    assert "Cheapest rate in your saved tariff: Boost at 0.0800 EUR/kWh, 02:00 to 04:00" in summary
    assert "Your bill runs from the 16th to the 15th." in summary
    assert "Night 0.1200 (23:00 to 08:00)" in summary
    entry = await finish(hass, confirm)
    await unload(hass, entry)


async def test_a_new_install_starts_in_dry_run_with_every_control_at_its_default(
    hass, hass_in_scenario, service_calls
):
    """The wizard does not ask for the tuning knobs, and nothing is sent until dry run is off."""
    result = await start(hass)
    _, confirm = await run_pages(hass, result, ["tariff"], tariff=TARIFF)
    assert "Dry run is on." in confirm["description_placeholders"]["summary"]

    entry = await finish(hass, confirm)
    try:
        assert entry.data["dry_run"] is True
        for key in (
            "surplus_divert_soc_pct",
            "surplus_divert_min_power_w",
            "cheap_rate_floor_soc",
            "skip_charge_soc_threshold_pct",
            "forecast_conservatism",
            "verbose_logging",
        ):
            assert key not in entry.data
        assert entry.runtime_data.is_dry_run is True
        registry = er.async_get(hass)
        switch = registry.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_dry_run")
        assert hass.states.get(switch).state == "on"
        assert service_calls["number.set_value"] == []
    finally:
        await unload(hass, entry)


async def test_no_setup_form_asks_for_a_control_or_a_retired_setting(
    hass, hass_in_scenario, service_calls
):
    remove_forecast(hass)
    result = await start(hass)
    names = {f["name"] for f in every_field(serialised(result))}
    result = await submit(manager(hass), result, pages=["tariff", "forecast", "hot_water"])
    while result["step_id"] != "confirm":
        names |= {f["name"] for f in every_field(serialised(result))}
        values = {
            "tariff": {**TARIFF, "rate_count": "1"},
            "tariff_rates": {"rate_period_1": {"rate": 0.1}},
        }.get(result["step_id"], {})
        result = await submit(manager(hass), result, **values)
    manager(hass).async_abort(result["flow_id"])

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
            "forecast_provider",
            "discovered_charger",
            "battery_min_soc_pct",
            "overnight_charge_target_pct",
            "car_efficiency_kwh_per_100km",
        }
    )
