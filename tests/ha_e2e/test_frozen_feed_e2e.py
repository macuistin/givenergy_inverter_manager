"""GivTCP entities that hold their last values trip the feed check, and only those."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from conftest import (
    BATTERY_POWER,
    CHEAP_NIGHT,
    GRID,
    LOAD,
    MIDDAY,
    SOC,
    SOLAR,
    ZAPPI_STATES,
    discover_the_charger,
    full_config_data,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
    GIVTCP_FROZEN_AFTER_S,
)

ISSUE = repairs.ISSUE_GIVTCP_FEED_FROZEN
STEP = timedelta(seconds=30)
LIMIT = timedelta(seconds=GIVTCP_FROZEN_AFTER_S)
FEED = (SOLAR, SOC, BATTERY_POWER, GRID, LOAD)
SCENARIO = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


@pytest.fixture(autouse=True)
def _feed_never_frozen():
    """Override the conftest fixture: these tests are about the frozen-feed check being on."""


def _republish(hass) -> None:
    """GivTCP publishes every entity again with the same value and attributes."""
    for entity_id in FEED:
        state = hass.states.get(entity_id)
        hass.states.async_set(entity_id, state.state, state.attributes)


async def _load(hass, data: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=data or full_config_data(), unique_id="ab1234g567", version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _run(hass, entry, freezer, span: timedelta, *, publishing: bool) -> None:
    elapsed = timedelta(0)
    while elapsed < span:
        freezer.tick(STEP)
        elapsed += STEP
        if publishing:
            _republish(hass)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


def _a_sensor_state(hass, entry) -> str:
    registry = er.async_get(hass)
    sensor = next(
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id) if e.domain == "sensor"
        and not e.disabled
    )
    return hass.states.get(sensor.entity_id).state


async def _unload(hass, entry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@SCENARIO
async def test_a_frozen_feed_trips_and_clears_when_it_moves_again(
    hass_in_scenario, service_calls, freezer, caplog
):
    hass = hass_in_scenario
    entry = await _load(hass)
    coordinator = entry.runtime_data
    assert coordinator.last_update_success is True

    with caplog.at_level(logging.WARNING):
        await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)

    assert coordinator.last_update_success is False
    assert coordinator.last_exception.translation_key == "givtcp_frozen"
    assert coordinator._last_update is None, "no energy is added across the gap"
    assert _a_sensor_state(hass, entry) == "unavailable"
    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    frozen_warnings = [r for r in caplog.records if "GivTCP data is frozen" in r.message]
    assert len(frozen_warnings) == 1
    assert "not unavailable" in frozen_warnings[0].message

    await _run(hass, entry, freezer, STEP, publishing=True)

    assert coordinator.last_update_success is True
    assert _a_sensor_state(hass, entry) != "unavailable"
    assert _issue(hass) is None
    await _unload(hass, entry)


@SCENARIO
async def test_a_steady_feed_that_is_still_published_never_trips(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)

    # Twice the limit of the same readings, each one published again every cycle.
    await _run(hass, entry, freezer, LIMIT * 2, publishing=True)

    assert entry.runtime_data.last_update_success is True
    assert _issue(hass) is None
    await _unload(hass, entry)


@SCENARIO
async def test_a_feed_that_pauses_for_less_than_the_limit_does_not_trip(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)

    await _run(hass, entry, freezer, LIMIT - 2 * STEP, publishing=False)

    assert entry.runtime_data.last_update_success is True
    assert _issue(hass) is None
    await _unload(hass, entry)


@SCENARIO
async def test_a_unchanged_value_reported_again_counts_as_reported(hass_in_scenario, freezer):
    """The signal is last_reported, which Home Assistant moves even when nothing changed."""
    hass = hass_in_scenario
    first = hass.states.get(SOC)
    reported, changed, value = first.last_reported, first.last_changed, first.state
    freezer.tick(timedelta(minutes=5))
    _republish(hass)
    after = hass.states.get(SOC)

    assert after.state == value
    assert after.last_changed == changed
    assert after.last_reported == reported + timedelta(minutes=5)


@SCENARIO
async def test_dry_run_trips_and_clears_the_same_way(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    entry = await _load(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DRY_RUN: True})
    await hass.async_block_till_done()
    assert entry.runtime_data.is_dry_run is True

    await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)
    assert entry.runtime_data.last_update_success is False
    assert _issue(hass) is not None

    await _run(hass, entry, freezer, STEP, publishing=True)
    assert entry.runtime_data.last_update_success is True
    assert _issue(hass) is None
    await _unload(hass, entry)


@SCENARIO
async def test_the_held_charge_plan_survives_the_freeze_and_resumes(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)
    coordinator = entry.runtime_data
    held = coordinator._held_charge.decision
    assert held is not None
    published_at = coordinator._held_charge.published_at

    await _run(hass, entry, freezer, LIMIT + 10 * STEP, publishing=False)
    assert coordinator.last_update_success is False
    assert coordinator._held_charge.decision is held

    await _run(hass, entry, freezer, STEP, publishing=True)
    assert coordinator.last_update_success is True
    assert coordinator._held_charge.decision is not None
    assert coordinator._held_charge.decision.target_soc == held.target_soc
    assert coordinator._held_charge.published_at == published_at
    await _unload(hass, entry)


@SCENARIO
async def test_no_charge_window_or_target_is_written_while_frozen(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)
    coordinator = entry.runtime_data
    calls = {
        f"{d}.{s}": async_mock_service(hass, d, s)
        for d, s in (("number", "set_value"), ("select", "select_option"), ("switch", "turn_on"))
    }

    await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)
    for sent in calls.values():
        sent.clear()  # anything before the freeze tripped was a live cycle, such as the immersion
    coordinator._backend.writer.last_write_time.clear()
    coordinator._write_charge_target_to_inverter(dt_util.utcnow())
    await hass.async_block_till_done()
    assert {name: len(c) for name, c in calls.items()} == dict.fromkeys(calls, 0)

    await _run(hass, entry, freezer, STEP, publishing=True)
    coordinator._write_charge_target_to_inverter(dt_util.utcnow())
    await hass.async_block_till_done()
    assert calls["number.set_value"], "the write goes ahead once the feed moves"
    await _unload(hass, entry)


@SCENARIO
async def test_a_feed_already_frozen_at_setup_retries_instead_of_planning(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    freezer.tick(LIMIT + 4 * STEP)  # every state was last reported 10 minutes ago

    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), unique_id="ab1234g567", version=1
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY


@SCENARIO
async def test_an_install_without_the_optional_devices_trips_and_clears_quietly(
    hass_in_scenario, service_calls, freezer, caplog
):
    hass = hass_in_scenario
    data = full_config_data()
    del data[CONF_IMMERSION_SWITCH]
    del data[CONF_IMMERSION_TEMP_SENSOR]
    entry = await _load(hass, data)

    with caplog.at_level(logging.ERROR):
        await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)
        assert _issue(hass) is not None
        await _run(hass, entry, freezer, STEP, publishing=True)

    assert _issue(hass) is None
    assert entry.runtime_data._ev_charger is None
    assert [i.issue_id for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN] == []
    # Home Assistant logs the failed cycles themselves, as it does for a silent feed.
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r for r in errors if "Error fetching" not in r.message] == []
    await _unload(hass, entry)


@SCENARIO
async def test_a_charger_added_while_frozen_is_found_once_the_feed_moves(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = await _load(hass)
    await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)
    assert _issue(hass) is not None

    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    await _run(hass, entry, freezer, STEP, publishing=True)
    await discover_the_charger(hass, entry)

    assert entry.runtime_data.last_update_success is True
    assert entry.runtime_data._ev_charger is not None
    assert _issue(hass) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_unloading_while_frozen_clears_the_repair(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    entry = await _load(hass)
    await _run(hass, entry, freezer, LIMIT + 4 * STEP, publishing=False)
    assert _issue(hass) is not None

    await _unload(hass, entry)

    assert _issue(hass) is None
