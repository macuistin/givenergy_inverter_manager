"""Run the coordinator and check what the sensor platform actually does at runtime."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from conftest import (
    CHARGE_START,
    ENABLE_SCHEDULE,
    ENABLE_TARGET,
    IMMERSION_SWITCH,
    MIDDAY,
    TARGET_SOC,
    full_config_data,
)
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, DOMAIN
from custom_components.givenergy_inverter_manager.sensor import (
    SENSOR_DESCRIPTIONS,
    reset_period_of,
)

INTEGRATION_LOGGER = "custom_components.givenergy_inverter_manager"
BAD_LOG_FRAGMENTS = (
    "does not generate unique IDs",
    "ValueError",
    "Traceback",
    "has set last_reset",
    "value_fn raised",
)


def _bad_records(caplog) -> list[str]:
    """Error-level records plus any record that mentions a known bad pattern."""
    return [
        f"{r.levelname} {r.name}: {r.getMessage()}"
        for r in caplog.records
        if r.levelno >= logging.ERROR
        or any(fragment in r.getMessage() for fragment in BAD_LOG_FRAGMENTS)
        or (r.exc_info and r.exc_info[0] is ValueError)
    ]


async def _refresh(hass, entry, times: int = 2) -> None:
    """Drive the coordinator the way the 30 s timer would."""
    for _ in range(times):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_refresh_has_no_unique_id_or_state_attribute_errors(hass, loaded_entry, caplog):
    """(b) Setup plus refreshes log no duplicate ID warning and no sensor ValueError."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    caplog.set_level(logging.DEBUG, logger="homeassistant.helpers.entity_platform")
    caplog.set_level(logging.DEBUG, logger="homeassistant.components.sensor")

    await _refresh(hass, loaded_entry)

    assert _bad_records(caplog) == []
    assert "does not generate unique IDs" not in caplog.text


async def test_sensor_state_attributes_render_after_refresh(hass, loaded_entry, caplog):
    """Every enabled sensor writes a state, so HA could build its state attributes."""
    await _refresh(hass, loaded_entry)

    registry = er.async_get(hass)
    missing = []
    for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id):
        if entry.domain != "sensor" or entry.disabled:
            continue
        state = hass.states.get(entry.entity_id)
        if state is None:
            missing.append(entry.entity_id)
            continue
        # Daily totals expose last_reset only for state_class total.
        if "last_reset" in state.attributes:
            assert state.attributes.get("state_class") == "total", entry.entity_id
    assert missing == []
    assert _bad_records(caplog) == []


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_daily_totals_expose_last_reset_after_midnight(hass, loaded_entry, caplog, freezer):
    """After the midnight reset, total sensors publish last_reset and nothing else does."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    caplog.set_level(logging.DEBUG, logger="homeassistant.components.sensor")

    # Local midnight in Europe/Dublin (UTC+1 in June).
    freezer.move_to("2026-06-15 23:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data._last_reset_time.startswith("2026-06-16T00:00:00")

    await _refresh(hass, loaded_entry)

    registry = er.async_get(hass)
    total_sensors = {
        f"{loaded_entry.entry_id}_{d.key}"
        for d in SENSOR_DESCRIPTIONS
        if reset_period_of(d) and d.state_class == "total"
    }
    assert total_sensors, "expected daily total sensors"
    seen_last_reset = 0
    for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id):
        if entry.domain != "sensor" or entry.disabled:
            continue
        state = hass.states.get(entry.entity_id)
        assert state is not None, entry.entity_id
        if entry.unique_id in total_sensors:
            seen_last_reset += "last_reset" in state.attributes
        else:
            assert "last_reset" not in state.attributes, entry.entity_id
    assert seen_last_reset
    assert _bad_records(caplog) == []


@pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)
async def test_week_month_and_year_totals_report_their_period_start(hass, loaded_entry):
    """Monday 15 June 2026, bill day 16: each period sensor reports where its period began."""
    await _refresh(hass, loaded_entry)

    registry = er.async_get(hass)
    expected = {
        "week": "2026-06-15T00:00:00+01:00",
        "month": "2026-05-16T00:00:00+01:00",
        "year": "2026-01-01T00:00:00+00:00",
    }
    checked = 0
    for description in SENSOR_DESCRIPTIONS:
        period = reset_period_of(description)
        if period not in expected or not description.entity_registry_enabled_default:
            continue
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{loaded_entry.entry_id}_{description.key}"
        )
        state = hass.states.get(entity_id)
        assert state.attributes.get("state_class") == "total", description.key
        assert state.attributes.get("last_reset") == expected[period], description.key
        checked += 1
    assert checked >= 15


async def test_all_sensors_enabled_have_usable_state(hass, loaded_entry, caplog, scenario):
    """(c) Enable every integration-disabled sensor, reload, and check each one's state."""
    registry = er.async_get(hass)
    sensors = [
        e
        for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if e.domain == "sensor"
    ]
    disabled = [e for e in sensors if e.disabled]
    assert disabled, "expected some sensors to be disabled by default"

    for entry in disabled:
        registry.async_update_entity(entry.entity_id, disabled_by=None)
    # HA reloads the config entry shortly after an entity is enabled.
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED

    await _refresh(hass, loaded_entry)
    coordinator = loaded_entry.runtime_data
    data = coordinator.data
    assert data is not None

    descriptions = {f"{loaded_entry.entry_id}_{d.key}": d for d in SENSOR_DESCRIPTIONS}
    raising: list[str] = []
    no_state: list[str] = []
    unavailable_but_applicable: list[str] = []
    unknown: list[str] = []

    for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id):
        if entry.domain != "sensor":
            continue
        assert not entry.disabled, entry.entity_id
        desc = descriptions[entry.unique_id]

        # Call the description functions directly: native_value swallows exceptions.
        try:
            desc.value_fn(data)
            if desc.html_fn is not None:
                desc.html_fn(data)
            if desc.attrs_fn is not None:
                desc.attrs_fn(data)
        except Exception as exc:  # noqa: BLE001
            raising.append(f"{desc.key}: {type(exc).__name__}: {exc}")

        state = hass.states.get(entry.entity_id)
        if state is None:
            no_state.append(desc.key)
        elif state.state == STATE_UNAVAILABLE and desc.available_fn(data):
            unavailable_but_applicable.append(desc.key)
        elif state.state == "unknown":
            unknown.append(desc.key)

    print(f"[{scenario.name}] sensors reporting 'unknown': {sorted(unknown)}")
    assert raising == []
    assert no_state == []
    assert unavailable_but_applicable == []
    assert _bad_records(caplog) == []


async def test_writes_go_only_to_configured_entities(hass, loaded_entry, service_calls, scenario):
    """Mocked number/switch/select services only ever see the configured GivTCP targets."""
    await _refresh(hass, loaded_entry)

    allowed = {TARGET_SOC, ENABLE_TARGET, ENABLE_SCHEDULE, CHARGE_START, IMMERSION_SWITCH}
    written = {
        entity
        for calls in service_calls.values()
        for call in calls
        for entity in _entity_ids(call.data["entity_id"])
    }
    assert written <= allowed, written - allowed


async def test_dry_run_sends_no_writes(hass, hass_in_scenario, service_calls, config_entry):
    """Dry run still computes decisions but never calls a write service."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**full_config_data(), CONF_DRY_RUN: True}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _refresh(hass, config_entry)

    try:
        assert config_entry.state is ConfigEntryState.LOADED
        assert config_entry.runtime_data.is_dry_run
        assert {k: len(v) for k, v in service_calls.items()} == {
            "number.set_value": 0,
            "switch.turn_on": 0,
            "switch.turn_off": 0,
            "select.select_option": 0,
        }
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


def _entity_ids(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


async def test_night_survival_confidence_explains_its_level(hass, loaded_entry):
    """The detail view of Night Survival Confidence says why it is Safe, Warning or Critical."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_night_survival_confidence"
    )
    assert entity_id
    registry.async_update_entity(entity_id, disabled_by=None)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()
    await _refresh(hass, loaded_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state in ("Safe", "Warning", "Critical")
    assert state.attributes["explanation"].startswith(state.state)
    assert state.attributes["minimum_soc"] == loaded_entry.runtime_data.data.battery_min_soc
    assert state.attributes["warning_below_soc"] > state.attributes["minimum_soc"]
    assert "estimated_soc_at_sunrise" in state.attributes
