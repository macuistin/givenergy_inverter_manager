"""The last_reset of an accumulating sensor, and what a sensor shows without data."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import MIDDAY
from homeassistant.components.sensor import DATA_COMPONENT


@pytest.fixture
def scenario():
    return MIDDAY


def _accumulating_sensor(hass):
    """A sensor of the integration that resets daily, found by its last_reset attribute."""
    for state in hass.states.async_all("sensor"):
        if "last_reset" in state.attributes and state.entity_id.startswith(
            "sensor.givenergy_inverter_manager"
        ):
            return hass.data[DATA_COMPONENT].get_entity(state.entity_id)
    raise AssertionError("no accumulating sensor found")


async def test_last_reset_is_the_start_of_the_period_the_coordinator_stored(
    hass, loaded_entry, service_calls
):
    sensor = _accumulating_sensor(hass)
    loaded_entry.runtime_data.data.last_reset_time = "2026-06-15T00:00:00+01:00"

    assert sensor.last_reset == datetime.fromisoformat("2026-06-15T00:00:00+01:00")


async def test_a_stored_reset_without_a_zone_is_read_as_utc(hass, loaded_entry, service_calls):
    sensor = _accumulating_sensor(hass)
    loaded_entry.runtime_data.data.last_reset_time = "2026-06-15T00:00:00"

    assert sensor.last_reset == datetime(2026, 6, 15, tzinfo=UTC)


@pytest.mark.parametrize("stored", ["", "not a date"])
async def test_no_reset_is_reported_for_a_missing_or_unreadable_time(
    hass, loaded_entry, service_calls, stored
):
    sensor = _accumulating_sensor(hass)
    loaded_entry.runtime_data.data.last_reset_time = stored

    assert sensor.last_reset is None


async def test_a_sensor_without_data_has_no_reset_and_no_attributes(
    hass, loaded_entry, service_calls
):
    sensor = _accumulating_sensor(hass)
    loaded_entry.runtime_data.data = None

    assert sensor.last_reset is None
    assert sensor.extra_state_attributes is None
