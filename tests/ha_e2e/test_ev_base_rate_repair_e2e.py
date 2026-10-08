"""A car charging from the grid at the base rate raises a repair, and only then."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import (
    CHEAP_NIGHT,
    GRID,
    LOAD,
    MIDDAY,
    ZAPPI_STATES,
    discover_the_charger,
    full_config_data,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import (
    DOMAIN,
    EV_BASE_RATE_ALERT_DELAY_S,
)

ISSUE = repairs.ISSUE_EV_BASE_RATE_CHARGING
DELAY = timedelta(seconds=EV_BASE_RATE_ALERT_DELAY_S)
STEP = timedelta(seconds=60)

# House load 800 W plus the car at 7.2 kW, all imported from the grid (GivTCP: negative import).
GRID_CHARGE = {"grid_w": -8000.0, "load_w": 8000.0, "solar_w": 0.0, "battery_w": 0.0}
# 13:00 local in June, in the base-rate band (Day).
BASE_BAND = replace(MIDDAY, name="ev_base_band", **GRID_CHARGE)
# 02:30 in December, inside Nightboost.
CHEAP_BAND = replace(CHEAP_NIGHT, name="ev_cheap_band", **GRID_CHARGE)
# 22:50 in December: Day until 23:00, then Night. A session started now crosses the boundary.
BEFORE_NIGHT = replace(CHEAP_NIGHT, name="ev_before_night", frozen_utc="2026-12-15 22:50:00+00:00", **GRID_CHARGE)
# 07:56 in December: Night until 08:00, then Day.
BEFORE_DAY = replace(CHEAP_NIGHT, name="ev_before_day", frozen_utc="2026-12-15 07:56:00+00:00", **GRID_CHARGE)

CHARGING = {
    **ZAPPI_STATES,
    "sensor.myenergi_zappi_plug_status": "EV Connected",
    "sensor.myenergi_zappi_status": "Boosting",
    "sensor.myenergi_zappi_internal_load_ct1": "7200",
    "sensor.myenergi_zappi_charge_added_session": "3.2",
    "select.myenergi_zappi_charge_mode": "Fast",
}
STOPPED = {
    **CHARGING,
    "sensor.myenergi_zappi_status": "Paused",
    "sensor.myenergi_zappi_internal_load_ct1": "0",
}


def _publish(hass, states: dict[str, str]) -> None:
    for entity_id, state in states.items():
        hass.states.async_set(entity_id, state)


async def _load(hass, *, charger: dict[str, str] | None = CHARGING) -> MockConfigEntry:
    if charger:
        _publish(hass, charger)
    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), unique_id="ab1234g567", version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    if charger:
        await discover_the_charger(hass, entry)
        assert entry.runtime_data._ev_charger is not None
    return entry


async def _run_for(hass, entry, freezer, span: timedelta) -> None:
    elapsed = timedelta(0)
    while elapsed < span:
        freezer.tick(STEP)
        elapsed += STEP
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def _unload(hass, entry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_a_grid_charge_in_the_base_rate_band_raises_a_repair_after_the_delay(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)

    await _run_for(hass, entry, freezer, DELAY - STEP)
    assert _issue(hass) is None

    await _run_for(hass, entry, freezer, 2 * STEP)
    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    assert issue.translation_placeholders == {
        "power_kw": "7.2",
        "rate_name": "Day",
        "next_cheap_start": "23:00",
    }
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_the_repair_stays_dismissed_for_the_rest_of_the_session(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)
    await _run_for(hass, entry, freezer, DELAY + STEP)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE, True)

    await _run_for(hass, entry, freezer, DELAY * 2)

    assert _issue(hass).dismissed_version is not None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_the_repair_clears_when_the_session_ends(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    entry = await _load(hass)
    await _run_for(hass, entry, freezer, DELAY + STEP)
    assert _issue(hass) is not None

    _publish(hass, STOPPED)
    await _run_for(hass, entry, freezer, STEP)

    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [CHEAP_BAND], ids=lambda s: s.name)
async def test_a_grid_charge_in_a_cheap_band_raises_nothing(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    entry = await _load(hass)

    await _run_for(hass, entry, freezer, DELAY * 3)

    assert entry.runtime_data.data.is_on_base_rate is False
    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_a_charge_on_solar_in_the_base_rate_band_raises_nothing(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    hass.states.async_set(GRID, 2500.0)  # exporting: the car runs on solar
    hass.states.async_set(LOAD, 8000.0)
    entry = await _load(hass)

    await _run_for(hass, entry, freezer, DELAY * 3)

    assert entry.runtime_data.data.is_on_base_rate is True
    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BEFORE_NIGHT], ids=lambda s: s.name)
async def test_a_session_that_crosses_into_a_cheap_band_clears_the_repair(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)

    await _run_for(hass, entry, freezer, DELAY + STEP)  # 22:56, still in the Day band
    assert _issue(hass) is not None

    await _run_for(hass, entry, freezer, 5 * STEP)  # 23:01, Night has started
    assert entry.runtime_data.data.is_on_base_rate is False
    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BEFORE_DAY], ids=lambda s: s.name)
async def test_a_session_that_crosses_into_the_base_rate_band_raises_after_the_delay(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)

    await _run_for(hass, entry, freezer, 6 * STEP)  # 08:02, two minutes into Day
    assert entry.runtime_data.data.is_on_base_rate is True
    assert _issue(hass) is None

    await _run_for(hass, entry, freezer, DELAY)
    assert _issue(hass) is not None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_an_install_with_no_charger_creates_and_evaluates_nothing(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass, charger=None)

    await _run_for(hass, entry, freezer, DELAY * 3)

    assert entry.runtime_data._ev_charger is None
    assert entry.runtime_data.data.is_on_base_rate is True
    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [BASE_BAND], ids=lambda s: s.name)
async def test_a_charger_that_appears_later_is_watched_from_then(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass, charger=None)
    await _run_for(hass, entry, freezer, DELAY)
    assert _issue(hass) is None

    _publish(hass, CHARGING)
    await discover_the_charger(hass, entry)
    await _run_for(hass, entry, freezer, DELAY + STEP)

    assert _issue(hass) is not None
    await _unload(hass, entry)
