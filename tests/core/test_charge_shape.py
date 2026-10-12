"""The charge simulation spreads the forecast with the forecast's own shape when it has one.

The tests assert the direction of the effect, not exact numbers. A west facing day lands its
solar late, so the battery runs lower before it and tonight needs more charge. An east facing
day is the other way round. With no shape, or an invalid one, the bell curve centred on 13:00
is used and nothing changes.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.rules import (
    SHAPE_REASON,
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
    usable_solar_shape,
)
from custom_components.givenergy_inverter_manager.core.seasons import SeasonRules
from custom_components.givenergy_inverter_manager.core.solar_shape import valid_shape

# A June night, outside the winter and shoulder months.
NIGHT = datetime(2031, 6, 15, 23, 30)
INPUTS = ChargeInputs(
    current_soc=30.0,
    battery_capacity_kwh=10.0,
    min_soc=10,
    skip_charge_threshold=90,
    car_plugged_in=False,
    inverter_max_kw=5.0,
    average_daily_consumption_kwh=10.0,
    cheapest_rate=0.1,
)


def bell(centre: float, spread: float) -> tuple[float, ...]:
    raw = [
        math.exp(-0.5 * ((slot / 2 - centre) / spread) ** 2) if 6 <= slot / 2 <= 20 else 0.0
        for slot in range(48)
    ]
    return valid_shape(raw)


EAST = bell(10, 2)
WEST = bell(16, 2)
FLAT = valid_shape([1.0] * 48)


def decide(shape, kwh: float | None = 8.0, inputs: ChargeInputs = INPUTS, when=NIGHT):
    return calculate_overnight_charge_target(
        inputs, SolarForecast(forecast_kwh=kwh, solar_shape=shape), when
    )


class TestTheDirectionOfTheEffect:
    def test_a_west_day_needs_more_charge_than_the_standard_curve(self):
        assert decide(WEST).target_soc > decide(None).target_soc

    def test_an_east_day_needs_less(self):
        assert decide(EAST).target_soc < decide(None).target_soc

    def test_a_flat_day_needs_the_least(self):
        assert decide(FLAT).target_soc < decide(EAST).target_soc

    @pytest.mark.parametrize("kwh", [8.0, 14.0, 20.0])
    def test_west_is_above_east_at_any_forecast_size(self, kwh):
        assert decide(WEST, kwh).target_soc > decide(EAST, kwh).target_soc

    def test_the_shape_changes_when_the_solar_arrives_not_how_much(self):
        # The total is the same. A shape with the standard curve's own shape gives its answer.
        standard = decide(None)
        same_shape = decide(bell(13, 3.5))
        assert abs(standard.target_soc - same_shape.target_soc) <= 1


class TestTheReason:
    def test_the_reason_says_so_only_when_a_shape_was_used(self):
        assert SHAPE_REASON in decide(WEST).reason
        assert SHAPE_REASON not in decide(None).reason

    def test_a_reason_without_a_shape_is_what_it_was_before(self):
        assert decide(None).reason.endswith("(forecast integration). Target 41%.")


class TestWhenTheShapeIsNotUsed:
    @pytest.mark.parametrize(
        "bad",
        [(1.0,) * 47, (1.0,) * 49, (0.0,) * 48, (-1.0,) + (1.0,) * 47, (math.nan,) * 48, "shape"],
        ids=["short", "long", "zeros", "negative", "nan", "text"],
    )
    def test_an_invalid_shape_falls_back_without_raising(self, bad):
        fallback = decide(None)
        result = decide(bad)
        assert result.target_soc == fallback.target_soc
        assert result.reason == fallback.reason

    def test_the_seasonal_estimate_has_no_shape_to_follow(self):
        with_shape = decide(WEST, kwh=None)
        without = decide(None, kwh=None)
        assert with_shape.target_soc == without.target_soc
        assert SHAPE_REASON not in with_shape.reason
        assert usable_solar_shape(SolarForecast(forecast_kwh=None, solar_shape=WEST)) is None

    def test_a_skipped_night_does_not_simulate_so_it_says_nothing_of_the_shape(self):
        full = replace(INPUTS, current_soc=95.0)
        result = decide(WEST, kwh=25.0, inputs=full)
        assert result.skip_charge
        assert SHAPE_REASON not in result.reason

    def test_a_winter_night_charges_to_the_cap_whatever_the_shape(self):
        winter = datetime(2031, 12, 15, 23, 30)
        assert decide(WEST, when=winter).target_soc == decide(None, when=winter).target_soc

    def test_a_winter_month_that_plans_from_the_forecast_uses_the_shape(self):
        seasons = SeasonRules(
            winter_months=(12,), shoulder_months=(), winter_uses_forecast=True
        )
        winter = datetime(2031, 12, 15, 23, 30)
        inputs = replace(INPUTS, seasons=seasons)
        assert SHAPE_REASON in decide(WEST, inputs=inputs, when=winter).reason
