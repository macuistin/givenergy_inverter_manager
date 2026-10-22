"""The setup wizard against a real flow manager: the first screen, how many screens, the order of
the pages, last_step and what is stored when.

What is detected, the inverter paths and the rate rows are in test_config_flow_detect_e2e.py.
"""

from __future__ import annotations

import itertools

import pytest
from conftest import (
    CAPACITY,
    FORECAST,
    MIDDAY,
    ZAPPI_STATES,
)
from homeassistant.config_entries import ConfigEntryState
from setup_support import ROWS, TARIFF, finish, manager, remove_forecast, run_pages, start, unload
from wizard_support import field_names, initial_data, serialised, submit

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_CAPACITY,
    DOMAIN,
)


@pytest.fixture
def scenario():
    return MIDDAY


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
    assert "Inverter: GivTCP ab1234g567 (hybrid inverter), all sensors found and used." in found
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
    _, confirm = await run_pages(hass, result, [], inverter_max_output_kw=5.0)
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


async def test_setup_reads_capacity_and_output_from_the_givtcp_sensors(
    hass, hass_in_scenario, service_calls
):
    hass.states.async_set(CAPACITY, 19.05, {"unit_of_measurement": "kWh"})
    rate = CAPACITY.replace("battery_capacity_kwh", "invertor_max_inv_rate")
    hass.states.async_set(rate, 3600, {"unit_of_measurement": "W"})
    result = await start(hass)
    assert "battery_capacity_kwh" not in field_names(result)
    assert "inverter_max_output_kw" not in field_names(result)

    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.data["battery_capacity_entity"] == CAPACITY
        assert entry.data["inverter_max_output_entity"] == rate
        assert entry.data[CONF_BATTERY_CAPACITY] == 19.05
        assert entry.data["inverter_max_output_kw"] == 3.6
    finally:
        await unload(hass, entry)
