"""Our overnight charge target on the four test scenarios of the PALM specification (SPEC-001).

This pins what our simulation does today. It does not assert the other method's numbers, and it
changes no behaviour. The two methods aim at the same outcome by different routes, and the
differences below are recorded for the maintainer to read (issue 341 has the comparison).

The setup is the specification's: capacity 10 kWh, reserve 4%, the grid charge ends after
half-hour 9, the house draws 0.3 kWh in every half hour after the window, a summer month. Solar
for a day is a shape over 07:00 to 17:00 scaled per scenario, 11.15 kWh at scale 1, with the
low estimate at half the middle and the high at 1.25 times it. The specification's weight picks
a point between the three estimates. Weight 10 is the low estimate, 35 is 37.5% of the way
from the middle to the low, 50 is the middle, and 70 is half way from the middle to the high.
Our forecast blend only goes toward the low estimate (our conservatism, 0 to 1), so weights 10
and 35 map to conservatism 1.0 and 0.375, and weights 50 and 70 are a plain forecast of the
blended kWh.

Targets, ours then the specification's published ones (scenario, weight 10, 35, 50, 70):

    A  normal           63 28 13  9   |  96 69 49 35
    B  dull then sunny  80 24  9  9   | 100 89 79 39
    C  very sunny       19  9  9  9   |  59 34 34 33
    D  no sun          100 100 100 100 | 100 100 100 100
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import CHARGE_MIN_TARGET_HEADROOM_PCT
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
)

SHAPE = (
    0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 1.00, 1.05, 1.05,
    1.00, 0.90, 0.80, 0.65, 0.50, 0.35, 0.20, 0.10, 0.05, 0.00,
)  # fmt: skip
DAY_KWH = sum(SHAPE)  # 11.15
LOW_OF_MIDDLE, HIGH_OF_MIDDLE = 0.5, 1.25
RESERVE_PCT = 4
CAPACITY_KWH = 10.0
WINDOW_END_INDEX = 9
LOAD_PER_SLOT_KWH = 0.3
PROFILE = [0.0] * (WINDOW_END_INDEX + 1) + [LOAD_PER_SLOT_KWH] * (47 - WINDOW_END_INDEX)
JUNE = datetime(2031, 6, 15, 22, 0, tzinfo=timezone.utc)

SCENARIOS = {"A": (1.0, 1.0), "B": (0.5, 2.2), "C": (1.8, 1.8), "D": (0.0, 0.0)}
WEIGHTS = (10, 35, 50, 70)
# How far toward the low estimate each weight below 50 goes: all of it at 10, 37.5% at 35.
TOWARD_LOW = {10: 1.0, 35: 0.375}

# What our simulation gives today, by scenario and weight.
OURS = {
    ("A", 10): 63, ("A", 35): 28, ("A", 50): 13, ("A", 70): 9,
    ("B", 10): 80, ("B", 35): 24, ("B", 50): 9, ("B", 70): 9,
    ("C", 10): 19, ("C", 35): 9, ("C", 50): 9, ("C", 70): 9,
    ("D", 10): 100, ("D", 35): 100, ("D", 50): 100, ("D", 70): 100,
}  # fmt: skip


def _blend(middle_kwh: float, weight: int) -> float:
    """The specification's blend of the three estimates for a weight, as a plain kWh."""
    low, high = LOW_OF_MIDDLE * middle_kwh, HIGH_OF_MIDDLE * middle_kwh
    low_factor = max(0, 50 - weight)
    high_factor = max(0, weight - 50)
    middle_factor = weight - 10 if weight <= 50 else 90 - weight
    total = low_factor + middle_factor + high_factor
    return (low * low_factor + middle_kwh * middle_factor + high * high_factor) / total


def _our_target(day1_scale: float, day2_scale: float, weight: int) -> int:
    middle1, middle2 = day1_scale * DAY_KWH, day2_scale * DAY_KWH
    if weight in TOWARD_LOW:
        forecast = SolarForecast(
            forecast_kwh=middle1,
            forecast_kwh_p10=LOW_OF_MIDDLE * middle1,
            forecast_conservatism=TOWARD_LOW[weight],
            forecast_kwh_d2=_blend(middle2, weight),
        )
    else:
        forecast = SolarForecast(
            forecast_kwh=_blend(middle1, weight), forecast_kwh_d2=_blend(middle2, weight)
        )
    inputs = ChargeInputs(
        current_soc=10.0,  # low, so the skip rule is not in play
        battery_capacity_kwh=CAPACITY_KWH,
        min_soc=RESERVE_PCT,
        skip_charge_threshold=101,
        car_plugged_in=False,
        inverter_max_kw=5.0,
        average_daily_consumption_kwh=sum(PROFILE),
        cheapest_rate=0.1,
        load_profile=PROFILE,
    )
    return calculate_overnight_charge_target(inputs, forecast, JUNE).target_soc


class TestTheScenarios:
    def test_the_specifications_shape_is_11_15_kwh_a_day(self):
        assert DAY_KWH == pytest.approx(11.15)

    @pytest.mark.parametrize(("scenario", "weight"), sorted(OURS))
    def test_our_target_is_pinned(self, scenario, weight):
        day1, day2 = SCENARIOS[scenario]

        assert _our_target(day1, day2, weight) == OURS[(scenario, weight)]

    def test_a_dark_day_charges_to_100_in_both_methods_at_every_weight(self):
        assert {_our_target(0.0, 0.0, w) for w in WEIGHTS} == {100}

    def test_a_more_cautious_weight_never_lowers_our_target(self):
        for scenario, (day1, day2) in SCENARIOS.items():
            targets = [_our_target(day1, day2, w) for w in WEIGHTS]
            assert targets == sorted(targets, reverse=True), scenario


class TestQuestionsInTheSpecification:
    """Questions 2, 3, 5, 6 and 7 of section 2.10, answered by what our code does."""

    def test_q2_we_do_not_leave_room_for_solar_that_would_overflow(self):
        """With plenty of sun the target falls to the minimum plus its headroom, not to a floor."""
        target = _our_target(1.8, 1.8, 70)

        assert target == RESERVE_PCT + CHARGE_MIN_TARGET_HEADROOM_PCT

    def test_q3_the_day_after_correction_is_a_percentage_of_capacity_not_of_the_peak(self):
        """Ours takes half of the day-after forecast above 100% of capacity off the target.

        It applies whenever that forecast alone exceeds the capacity, and does not look at
        whether tomorrow's own peak is below 100%.
        """
        base = SolarForecast(forecast_kwh=6.0, forecast_kwh_d2=8.0)
        with_overmorrow = SolarForecast(forecast_kwh=6.0, forecast_kwh_d2=16.0)
        inputs = ChargeInputs(
            current_soc=10.0,
            battery_capacity_kwh=CAPACITY_KWH,
            min_soc=RESERVE_PCT,
            skip_charge_threshold=101,
            car_plugged_in=False,
            inverter_max_kw=5.0,
            average_daily_consumption_kwh=sum(PROFILE),
            cheapest_rate=0.1,
            load_profile=PROFILE,
        )

        plain = calculate_overnight_charge_target(inputs, base, JUNE)
        reduced = calculate_overnight_charge_target(inputs, with_overmorrow, JUNE)

        assert "Overmorrow" in reduced.reason
        assert "Overmorrow" not in plain.reason
        assert reduced.target_soc == max(RESERVE_PCT + CHARGE_MIN_TARGET_HEADROOM_PCT, plain.target_soc - 30)

    def test_q5_the_simulation_has_no_charge_rate_limit(self):
        """The same plan comes out whatever the inverter's maximum output is."""
        def target(kw: float) -> int:
            inputs = ChargeInputs(
                current_soc=10.0,
                battery_capacity_kwh=CAPACITY_KWH,
                min_soc=RESERVE_PCT,
                skip_charge_threshold=101,
                car_plugged_in=False,
                inverter_max_kw=kw,
                average_daily_consumption_kwh=sum(PROFILE),
                cheapest_rate=0.1,
                load_profile=PROFILE,
            )
            return calculate_overnight_charge_target(
                inputs, SolarForecast(forecast_kwh=9.0), JUNE
            ).target_soc

        assert target(0.5) == target(5.0) == target(15.0)

    def test_q6_a_missing_forecast_uses_the_seasonal_estimate_not_100(self):
        inputs = ChargeInputs(
            current_soc=10.0,
            battery_capacity_kwh=CAPACITY_KWH,
            min_soc=RESERVE_PCT,
            skip_charge_threshold=101,
            car_plugged_in=False,
            inverter_max_kw=5.0,
            average_daily_consumption_kwh=sum(PROFILE),
            cheapest_rate=0.1,
            load_profile=PROFILE,
        )

        decision = calculate_overnight_charge_target(
            inputs, SolarForecast(forecast_kwh=None, solar_fractions={6: 1.0}), JUNE
        )

        assert "seasonal estimate" in decision.reason
        assert decision.target_soc < 100

    def test_q7_a_winter_month_gives_the_same_decision_whether_or_not_it_is_a_dry_run(self):
        """The decision has no dry-run input, so a dry run shows what a live run would write."""
        january = datetime(2031, 1, 15, 22, 0, tzinfo=timezone.utc)
        inputs = ChargeInputs(
            current_soc=10.0,
            battery_capacity_kwh=CAPACITY_KWH,
            min_soc=RESERVE_PCT,
            skip_charge_threshold=101,
            car_plugged_in=False,
            inverter_max_kw=5.0,
            average_daily_consumption_kwh=sum(PROFILE),
            cheapest_rate=0.1,
        )

        decision = calculate_overnight_charge_target(inputs, SolarForecast(forecast_kwh=9.0), january)

        assert decision.target_soc == 100
        assert "Winter" in decision.reason
