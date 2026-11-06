"""What the entities a device is based on are doing, and when that is a fault."""

from datetime import UTC, datetime, timedelta

from custom_components.givenergy_inverter_manager.core.source_health import (
    SENSOR_STALE_AFTER_S,
    Source,
    describe,
    status,
)

NOW = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)


def _source(state="53.2", minutes=1, *, can_be_stale=True, role="water temperature"):
    return Source(role, "sensor.tank", state, NOW - timedelta(minutes=minutes), can_be_stale)


def test_a_source_reporting_recently_is_ok():
    assert status((_source(),), NOW) == ("ok", "")


def test_an_unavailable_source_is_an_error_naming_it():
    state, cause = status((_source("unavailable"),), NOW)
    assert state == "error"
    assert "(sensor.tank) is unavailable" in cause


def test_a_missing_source_is_an_error():
    missing = Source("heater switch", "switch.heater", None, None, False)
    assert status((missing,), NOW)[0] == "error"


def test_a_sensor_silent_for_over_an_hour_is_an_error():
    minutes = SENSOR_STALE_AFTER_S // 60 + 5
    state, cause = status((_source(minutes=minutes),), NOW)
    assert state == "error"
    assert f"{minutes} minutes" in cause


def test_a_switch_is_never_called_stale():
    assert status((_source("on", minutes=600, can_be_stale=False),), NOW)[0] == "ok"


def test_the_attributes_give_state_last_report_and_age():
    row = describe((_source(minutes=5),), NOW)[0]
    assert row["entity_id"] == "sensor.tank"
    assert row["state"] == "53.2"
    assert row["age_minutes"] == 5.0
    assert row["last_reported"] == (NOW - timedelta(minutes=5)).isoformat()
