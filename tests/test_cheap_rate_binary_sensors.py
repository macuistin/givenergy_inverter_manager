"""Cheapest Rate Active and Cheap Rate Active read the tariff state the engine publishes."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
)
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData


def _data(*, cheapest: bool, run_minutes: float | None) -> CoordinatorData:
    return CoordinatorData(is_on_cheapest_rate=cheapest, cheap_run_remaining_minutes=run_minutes)


class TestCheapestRateActive:
    def test_it_is_on_in_the_cheapest_period(self):
        assert values.cheapest_rate_active(_data(cheapest=True, run_minutes=90.0))

    def test_it_is_off_in_a_cheap_period_that_is_not_the_cheapest(self):
        assert not values.cheapest_rate_active(_data(cheapest=False, run_minutes=90.0))


class TestCheapRateActive:
    def test_it_is_on_anywhere_in_the_run_of_cheap_hours(self):
        assert values.cheap_rate_active(_data(cheapest=False, run_minutes=90.0))
        assert values.cheap_rate_active(_data(cheapest=True, run_minutes=30.0))

    def test_it_is_off_at_the_base_rate_and_with_no_timed_period(self):
        assert not values.cheap_rate_active(_data(cheapest=False, run_minutes=None))


def test_each_description_reads_its_own_function_and_is_keyed_for_translation():
    by_key = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}
    assert set(by_key) == {"cheapest_rate_active", "cheap_rate_active"}
    assert all(d.translation_key == d.key for d in by_key.values())
    boundary = _data(cheapest=False, run_minutes=45.0)
    assert by_key["cheapest_rate_active"].value_fn(boundary) is False
    assert by_key["cheap_rate_active"].value_fn(boundary) is True
