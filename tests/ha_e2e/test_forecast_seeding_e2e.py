"""A new install seeds its forecast accuracy history from a real Home Assistant recorder.

The recorder is the real one (the plugin's recorder_mock, an in-memory SQLite database). The
days are written the way Home Assistant writes them: states set at past times with the clock
frozen, then committed. Setup reads them back through the recorder's own history query.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import FORECAST, MIDDAY, PREFIX, set_givtcp_states
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance, session_scope
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    _STORAGE_VERSION,
    AccumulationState,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import DOMAIN

DUBLIN = ZoneInfo("Europe/Dublin")
SOLAR_TOTAL = f"sensor.{PREFIX}_pv_energy_today_kwh"
# MIDDAY freezes the clock at 13:00 on 15 June in Dublin.
TODAY = datetime(2026, 6, 15, tzinfo=DUBLIN).date()
KWH = {"unit_of_measurement": "kWh", "device_class": "energy"}

# days_ago: (the forecast for that day, held by the sensor the evening before; the solar total)
RECORDED_DAYS = {
    1: (20.0, 14.0),
    2: (18.5, 12.0),
    3: (22.0, 15.4),
    4: (9.0, 8.1),
    5: (16.0, 11.2),
    6: (25.0, 17.5),
    7: (14.0, 9.8),
    8: (19.0, 13.3),
    9: (21.0, 14.7),
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Start the recorder before hass, which the plugin's recorder fixtures require."""
    return None


@pytest.fixture
def scenario():
    return MIDDAY


def _local(days_ago: int, hour: int, minute: int = 0) -> datetime:
    day = TODAY - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DUBLIN)


async def _record_days(
    hass, freezer, days: dict[int, tuple[float | None, float | None]]
) -> None:
    """Write what the recorder would hold: the forecast each evening, the solar total each day.

    A day whose forecast is None records no new forecast, one whose total is None no total.
    """
    for days_ago, (forecast, actual) in sorted(days.items(), reverse=True):
        if forecast is not None:
            freezer.move_to(_local(days_ago + 1, 23, 50))
            hass.states.async_set(FORECAST, forecast, KWH)
        if actual is None:
            continue
        freezer.move_to(_local(days_ago, 12))
        hass.states.async_set(SOLAR_TOTAL, actual / 2, KWH)
        freezer.move_to(_local(days_ago, 21))
        hass.states.async_set(SOLAR_TOTAL, actual, KWH)
        freezer.move_to(_local(days_ago, 23, 59))
        hass.states.async_set(SOLAR_TOTAL, 0.0, KWH)  # the counter resets at midnight
    await async_wait_recording_done(hass)
    freezer.move_to(MIDDAY.frozen_utc)
    set_givtcp_states(hass, MIDDAY)


async def _reload_oldest_state_time(hass) -> None:
    """Make the recorder know its oldest state, as it does after a restart.

    Home Assistant records states in time order, so the first one it saw is the oldest. A
    test writes the past after the present and has to tell the recorder where the data begins.
    """
    instance = get_instance(hass)

    def reload() -> None:
        with session_scope(hass=hass, read_only=True) as session:
            instance.states_manager.load_from_db(session)

    await instance.async_add_executor_job(reload)


async def _setup(hass, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _reason_attributes(hass, entry) -> dict:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_overnight_charge_reason"
    )
    assert entity_id
    return dict(hass.states.get(entity_id).attributes)


def _expected_history(days: dict[int, tuple[float, float]]) -> list[dict]:
    """Oldest day first, as the store keeps it."""
    return [
        {"forecast": forecast, "actual": actual, "clipped": False}
        for _, (forecast, actual) in sorted(days.items(), reverse=True)
    ]


async def test_a_new_install_starts_with_the_recorded_days_and_applies_the_correction(
    hass, hass_in_scenario, service_calls, config_entry, freezer
):
    await _record_days(hass, freezer, RECORDED_DAYS)

    await _setup(hass, config_entry)

    acc = config_entry.runtime_data._acc
    assert acc.state.forecast_ratio_history == _expected_history(RECORDED_DAYS)
    attributes = _reason_attributes(hass, config_entry)
    assert attributes["accuracy_applied"] is True
    assert attributes["accuracy_usable_days"] == 9
    assert attributes["accuracy_days_stored"] == 9
    assert attributes["accuracy_status"].startswith("Applied: x0.")
    assert attributes["accuracy_status"].endswith("from 9 usable days")
    assert "recent accuracy" in config_entry.runtime_data.data.charge_decision.reason


async def test_a_few_recorded_days_show_the_correction_still_waiting(
    hass, hass_in_scenario, service_calls, config_entry, freezer
):
    await _record_days(hass, freezer, {n: RECORDED_DAYS[n] for n in (1, 2, 3)})

    await _setup(hass, config_entry)

    attributes = _reason_attributes(hass, config_entry)
    assert attributes["accuracy_status"] == "Waiting for data: 3 of 5 days"
    assert attributes["accuracy_days_stored"] == 3


async def test_a_day_without_a_recorded_solar_total_is_left_out(
    hass, hass_in_scenario, service_calls, config_entry, freezer
):
    days = {n: RECORDED_DAYS[n] for n in (1, 2, 3, 4, 5, 6)}
    await _record_days(hass, freezer, {**days, 3: (days[3][0], None)})

    await _setup(hass, config_entry)

    expected = _expected_history({n: v for n, v in days.items() if n != 3})
    assert config_entry.runtime_data._acc.state.forecast_ratio_history == expected


async def test_a_forecast_unchanged_since_before_the_window_still_pairs_with_each_day(
    hass, hass_in_scenario, service_calls, config_entry, freezer
):
    """The sensor kept one value for three weeks, so no state row falls inside the window."""
    await _record_days(
        hass,
        freezer,
        {20: (15.0, None), 3: (None, 8.0), 2: (None, 9.0), 1: (None, 10.0)},
    )
    await _reload_oldest_state_time(hass)

    await _setup(hass, config_entry)

    assert config_entry.runtime_data._acc.state.forecast_ratio_history == [
        {"forecast": 15.0, "actual": 8.0, "clipped": False},
        {"forecast": 15.0, "actual": 9.0, "clipped": False},
        {"forecast": 15.0, "actual": 10.0, "clipped": False},
    ]


async def test_no_recorded_history_leaves_the_correction_waiting(
    hass, hass_in_scenario, service_calls, config_entry
):
    await _setup(hass, config_entry)

    attributes = _reason_attributes(hass, config_entry)
    assert attributes["accuracy_status"] == "Waiting for data: 0 of 5 days"
    assert config_entry.runtime_data._acc.state.forecast_ratio_history == []


async def test_seeded_days_are_stored_so_a_restart_does_not_query_again(
    hass, hass_in_scenario, service_calls, config_entry, freezer, hass_storage
):
    await _record_days(hass, freezer, RECORDED_DAYS)

    await _setup(hass, config_entry)

    saved = hass_storage[_STORAGE_KEY]["data"]["forecast_ratio_history"]
    assert saved == _expected_history(RECORDED_DAYS)


async def test_a_stored_history_is_never_replaced_by_the_recorder(
    hass, hass_in_scenario, service_calls, config_entry, freezer, hass_storage
):
    kept = [{"forecast": 12.0, "actual": 9.0, "clipped": True}]
    state = AccumulationState()
    state.last_reset_iso = "2026-06-15T00:00:00+01:00"
    state.forecast_ratio_history = list(kept)
    hass_storage[_STORAGE_KEY] = {
        "version": _STORAGE_VERSION,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _serialize(state),
    }
    await _record_days(hass, freezer, RECORDED_DAYS)

    await _setup(hass, config_entry)

    assert config_entry.runtime_data._acc.state.forecast_ratio_history == kept


async def test_a_failing_recorder_query_does_not_stop_setup(
    hass, hass_in_scenario, service_calls, config_entry, freezer, monkeypatch
):
    def broken(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(
        "custom_components.givenergy_inverter_manager.forecast_seeding._recorded_states", broken
    )
    await _record_days(hass, freezer, RECORDED_DAYS)

    await _setup(hass, config_entry)

    assert config_entry.state.name == "LOADED"
    attributes = _reason_attributes(hass, config_entry)
    assert attributes["accuracy_status"] == "Waiting for data: 0 of 5 days"
