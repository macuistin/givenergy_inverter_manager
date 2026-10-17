"""The reason says so when the target written is the minimum plus headroom, not the simulation's.

On the night of 16 to 17 October the reason read "Target 71%" while 75 was written. A shoulder
month raises the minimum SoC to 70, the plan never targets less than the minimum plus 5 points,
and the reason did not mention it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_MIN_TARGET_HEADROOM_PCT,
    CHARGE_SHOULDER_MIN_SOC,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
)

JUNE = datetime(2031, 6, 15, 22, 0, tzinfo=timezone.utc)
OCTOBER = datetime(2031, 10, 15, 22, 0, tzinfo=timezone.utc)
SHOULDER_FLOOR = CHARGE_SHOULDER_MIN_SOC + CHARGE_MIN_TARGET_HEADROOM_PCT
SENTENCE = re.compile(r"Raised to (\d+)%, the minimum SoC plus 5 points of headroom\.")


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


def test_a_target_raised_to_the_shoulder_minimum_plus_headroom_says_so():
    decision = calculate_overnight_charge_target(
        _inputs(average_daily_consumption_kwh=1.0), SolarForecast(forecast_kwh=40.0), OCTOBER
    )

    assert decision.target_soc == SHOULDER_FLOOR
    found = SENTENCE.search(decision.reason)
    assert found
    assert int(found.group(1)) == decision.target_soc


def test_the_sentence_comes_after_the_simulations_own_target():
    decision = calculate_overnight_charge_target(
        _inputs(average_daily_consumption_kwh=1.0), SolarForecast(forecast_kwh=40.0), OCTOBER
    )

    assert decision.reason.index("Target ") < decision.reason.index("Raised to")


def test_a_target_above_the_minimum_plus_headroom_says_nothing_of_it():
    decision = calculate_overnight_charge_target(
        _inputs(average_daily_consumption_kwh=12.0), SolarForecast(forecast_kwh=3.0), OCTOBER
    )

    assert decision.target_soc > SHOULDER_FLOOR
    assert "headroom" not in decision.reason


def test_a_summer_target_raised_to_the_25_percent_floor_says_only_that():
    decision = calculate_overnight_charge_target(_inputs(), SolarForecast(forecast_kwh=40.0), JUNE)

    assert decision.reason.endswith("Raised to the 25% floor.")
    assert "headroom" not in decision.reason


def test_a_skipped_charge_says_nothing_of_headroom():
    decision = calculate_overnight_charge_target(
        _inputs(current_soc=90.0, skip_charge_threshold=50, average_daily_consumption_kwh=1.0),
        SolarForecast(forecast_kwh=40.0),
        OCTOBER,
    )

    assert decision.skip_charge is True
    assert "headroom" not in decision.reason
