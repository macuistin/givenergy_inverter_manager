"""A planned overnight target is never below 25%, the floor PALM holds in summer.

Before the floor, a day with plenty of sun planned the minimum SoC plus 5 points, 15% with the
default minimum of 10. The spike that compared the plan with SPEC-001 found ours 20 to 70 points
below the specification's on every sunny day, and this closes the part of that gap where the
target was lowest. The shoulder floor of 70% is already higher, so it is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_SHOULDER_MIN_SOC,
    CHARGE_SUMMER_MIN_TARGET_SOC,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
)

JUNE = datetime(2031, 6, 15, 22, 0, tzinfo=timezone.utc)
OCTOBER = datetime(2031, 10, 15, 22, 0, tzinfo=timezone.utc)


def _inputs(**changes) -> ChargeInputs:
    base = {
        "current_soc": 20.0,
        "battery_capacity_kwh": 10.0,
        "min_soc": 10,
        "skip_charge_threshold": 101,
        "car_plugged_in": False,
        "inverter_max_kw": 5.0,
        "average_daily_consumption_kwh": 2.0,
        "cheapest_rate": 0.1,
    }
    return ChargeInputs(**{**base, **changes})


def test_the_floor_is_25_percent():
    assert CHARGE_SUMMER_MIN_TARGET_SOC == 25


def test_a_very_sunny_summer_day_is_raised_to_the_floor_and_says_so():
    decision = calculate_overnight_charge_target(
        _inputs(), SolarForecast(forecast_kwh=40.0), JUNE
    )

    assert decision.target_soc == CHARGE_SUMMER_MIN_TARGET_SOC
    assert decision.reason.endswith("Raised to the 25% floor.")
    assert decision.skip_charge is False


def test_a_target_already_above_the_floor_is_left_alone_and_says_nothing_of_it():
    decision = calculate_overnight_charge_target(
        _inputs(average_daily_consumption_kwh=8.0), SolarForecast(forecast_kwh=3.0), JUNE
    )

    assert decision.target_soc > CHARGE_SUMMER_MIN_TARGET_SOC
    assert "floor" not in decision.reason


def test_a_minimum_soc_above_the_floor_already_holds_it_and_says_nothing_of_it():
    decision = calculate_overnight_charge_target(
        _inputs(min_soc=30), SolarForecast(forecast_kwh=40.0), JUNE
    )

    assert decision.target_soc >= 35
    assert "floor" not in decision.reason


def test_a_skipped_charge_is_not_raised_to_the_floor():
    decision = calculate_overnight_charge_target(
        _inputs(current_soc=90.0, skip_charge_threshold=50, average_daily_consumption_kwh=1.0),
        SolarForecast(forecast_kwh=40.0),
        JUNE,
    )

    assert decision.skip_charge is True
    assert decision.target_soc < CHARGE_SUMMER_MIN_TARGET_SOC
    assert "floor" not in decision.reason


def test_a_shoulder_month_keeps_its_own_higher_floor():
    decision = calculate_overnight_charge_target(
        _inputs(), SolarForecast(forecast_kwh=40.0), OCTOBER
    )

    assert decision.target_soc >= CHARGE_SHOULDER_MIN_SOC + 5
    assert "floor" not in decision.reason


@pytest.mark.parametrize("forecast_kwh", [0.0, 2.0, 40.0])
def test_the_target_never_falls_below_the_floor_in_summer(forecast_kwh):
    decision = calculate_overnight_charge_target(
        _inputs(), SolarForecast(forecast_kwh=forecast_kwh), JUNE
    )

    assert decision.target_soc >= CHARGE_SUMMER_MIN_TARGET_SOC
