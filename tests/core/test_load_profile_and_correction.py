"""Per-slot load profile, forecast correction factor and charge scenarios in rules.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_FORECAST_CORRECTION_MAX,
    CHARGE_FORECAST_CORRECTION_MIN,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    build_load_profile,
    forecast_correction_factor,
)
from tests.core.flat_rules import _simulate_min_soc, calculate_overnight_charge_target

# 2026-06-15 is a Monday.
_MONDAY = date(2026, 6, 15)


def _day(offset: int, per_slot: float = 0.4, coverage: float = 1.0, slots=None) -> dict:
    return {
        "date": (_MONDAY + timedelta(days=offset)).isoformat(),
        "slots": slots if slots is not None else [per_slot] * 48,
        "coverage": coverage,
    }


def _evening_heavy() -> list[float]:
    """Light load until 17:00, then heavy: 20 kWh a day in total."""
    return [0.1 if slot < 34 else 0.1 + (20 - 0.1 * 48) / 14 for slot in range(48)]


def _morning_heavy() -> list[float]:
    return [0.1 + (20 - 0.1 * 48) / 14 if slot < 14 else 0.1 for slot in range(48)]


class TestBuildLoadProfile:
    def test_none_without_history(self):
        assert build_load_profile([], 0) is None

    def test_none_with_one_complete_day(self):
        assert build_load_profile([_day(0)], 0) is None

    def test_two_complete_days_average(self):
        profile = build_load_profile([_day(0, 0.2), _day(1, 0.4)], 3)
        assert len(profile) == 48
        # newest weighs 1.0, older 0.85
        assert profile[0] == pytest.approx((0.4 * 1.0 + 0.2 * 0.85) / 1.85)

    def test_days_under_ninety_percent_coverage_skipped(self):
        history = [_day(0, 0.2), _day(1, 9.9, coverage=0.89), _day(2, 0.2)]
        profile = build_load_profile(history, 5)
        assert profile == pytest.approx([0.2] * 48)

    def test_exactly_ninety_percent_counts_as_complete(self):
        assert build_load_profile([_day(0, coverage=0.9), _day(1, coverage=0.9)], 0) is not None

    def test_partial_days_do_not_count_towards_minimum(self):
        history = [_day(0), _day(1, coverage=0.5), _day(2, coverage=0.2)]
        assert build_load_profile(history, 0) is None

    def test_prefers_same_weekday_with_three_or_more(self):
        # Mondays are 0.1, 8 and 15 June; every other day is 0.5
        history = [_day(-14, 0.1), _day(-13, 0.5), _day(-7, 0.1), _day(-6, 0.5), _day(0, 0.1)]
        profile = build_load_profile(history, 0)
        assert profile == pytest.approx([0.1] * 48)

    def test_two_same_weekday_days_fall_back_to_all_days(self):
        history = [_day(-7, 0.1), _day(-6, 0.5), _day(0, 0.1)]
        profile = build_load_profile(history, 0)
        assert profile[0] > 0.1

    def test_malformed_records_ignored(self):
        history = [{"date": "bad", "slots": [1.0] * 48, "coverage": 1.0}, {"slots": []}, _day(0)]
        assert build_load_profile(history, 0) is None


class TestSimulationUsesProfile:
    def test_none_profile_equals_flat_load(self):
        flat = _simulate_min_soc(60.0, 10.0, 20.0, 19.0)
        assert _simulate_min_soc(60.0, 10.0, 20.0, 19.0, None) == flat

    def test_flat_profile_matches_flat_load(self):
        flat = _simulate_min_soc(60.0, 10.0, 20.0, 19.0)
        profiled = _simulate_min_soc(60.0, 10.0, 20.0, 19.0, [1.0] * 48)
        assert profiled == pytest.approx(flat)

    def test_profile_is_scaled_to_average_daily_total(self):
        # A profile in different units gives the same result once scaled to 20 kWh
        small = [v / 10 for v in _evening_heavy()]
        a = _simulate_min_soc(60.0, 10.0, 20.0, 19.0, _evening_heavy())
        b = _simulate_min_soc(60.0, 10.0, 20.0, 19.0, small)
        assert a == pytest.approx(b)

    def test_unusable_profiles_fall_back_to_flat(self):
        flat = _simulate_min_soc(60.0, 10.0, 20.0, 19.0)
        for bad in ([0.0] * 48, [1.0] * 47, [-1.0] + [1.0] * 47):
            assert _simulate_min_soc(60.0, 10.0, 20.0, 19.0, bad) == flat


def _decide(**overrides):
    kwargs = {
        "current_soc": 30.0,
        "battery_capacity_kwh": 19.0,
        "forecast_kwh": 14.0,
        "inverter_max_kw": 5.0,
        "car_plugged_in": False,
        "min_soc": 10,
        "skip_charge_threshold": 75,
        "average_daily_consumption_kwh": 20.0,
        "cheapest_rate": 0.0965,
        "dt": datetime(2026, 6, 15, 22, 0),
    }
    kwargs.update(overrides)
    return calculate_overnight_charge_target(**kwargs)


class TestLoadProfileChangesTarget:
    def test_morning_heavy_profile_needs_more_charge_than_flat(self):
        flat = _decide()
        morning = _decide(load_profile=_morning_heavy())
        assert morning.target_soc > flat.target_soc
        assert "load profile" in morning.reason

    def test_evening_heavy_profile_needs_less_charge_than_flat(self):
        flat = _decide()
        evening = _decide(load_profile=_evening_heavy())
        assert evening.target_soc < flat.target_soc

    def test_no_profile_leaves_reason_unchanged(self):
        assert "load profile" not in _decide().reason


class TestForecastCorrectionFactor:
    @staticmethod
    def _rec(forecast, actual, clipped=False):
        return {"forecast": forecast, "actual": actual, "clipped": clipped}

    def test_none_below_five_usable_days(self):
        assert forecast_correction_factor([self._rec(10, 8)] * 4) is None

    def test_median_ratio(self):
        recs = [self._rec(10, a) for a in (7, 8, 9, 6, 8)]
        assert forecast_correction_factor(recs) == pytest.approx(0.8)

    def test_clipped_days_ignored(self):
        recs = [self._rec(10, 8)] * 4 + [self._rec(10, 3, clipped=True)]
        assert forecast_correction_factor(recs) is None

    def test_low_energy_days_ignored(self):
        recs = [self._rec(10, 8)] * 4 + [self._rec(0.4, 0.2), self._rec(10, 0.3)]
        assert forecast_correction_factor(recs) is None

    def test_clamped_low(self):
        assert forecast_correction_factor([self._rec(10, 2)] * 5) == pytest.approx(0.6)

    def test_clamped_high(self):
        assert forecast_correction_factor([self._rec(10, 20)] * 5) == pytest.approx(1.2)

    def test_median_resists_one_outlier(self):
        recs = [self._rec(10, 9)] * 4 + [self._rec(10, 1)]
        assert forecast_correction_factor(recs) == pytest.approx(0.9)


class TestForecastCorrectionApplied:
    def test_lower_factor_raises_target(self):
        plain = _decide()
        corrected = _decide(forecast_correction=0.7)
        assert corrected.target_soc > plain.target_soc
        assert corrected.forecast_kwh == pytest.approx(14.0 * 0.7)

    def test_none_and_one_leave_decision_identical(self):
        plain = _decide()
        assert _decide(forecast_correction=None) == plain
        assert _decide(forecast_correction=1.0) == plain

    def test_correction_applies_before_p10_blend(self):
        decision = _decide(
            forecast_correction=0.8, forecast_kwh_p10=6.0, forecast_conservatism=0.5
        )
        assert decision.forecast_kwh == pytest.approx(0.5 * 14.0 * 0.8 + 0.5 * 6.0)

    def test_not_applied_to_seasonal_estimate(self):
        with_factor = _decide(forecast_kwh=None, forecast_correction=0.6)
        without = _decide(forecast_kwh=None)
        assert with_factor == without


class TestConservatismWithoutP10:
    def test_reason_says_conservatism_is_unused(self):
        decision = _decide(forecast_conservatism=0.35)
        assert "no P10 forecast so conservatism is unused" in decision.reason

    def test_note_comes_after_the_accuracy_factor(self):
        decision = _decide(forecast_conservatism=0.35, forecast_correction=0.7)
        assert "x0.70 recent accuracy, no P10 forecast so conservatism is unused" in (
            decision.reason
        )

    def test_forecast_is_not_changed_by_the_note(self):
        assert _decide(forecast_conservatism=0.35).forecast_kwh == pytest.approx(14.0)

    def test_no_note_when_conservatism_is_zero(self):
        assert "conservatism" not in _decide(forecast_conservatism=0.0).reason

    def test_no_note_when_a_p10_forecast_is_present(self):
        decision = _decide(forecast_kwh_p10=8.0, forecast_conservatism=0.35)
        assert "conservatism is unused" not in decision.reason
        assert "P10/P50 blend" in decision.reason

    def test_no_note_for_the_seasonal_estimate(self):
        decision = _decide(forecast_kwh=None, forecast_conservatism=0.35)
        assert "conservatism" not in decision.reason


class TestMeasuredBias:
    """A forecast that ran about 30% high is corrected without reaching the 0.6 floor."""

    RATIOS = (0.62, 0.88, 1.13, 0.69, 0.66, 0.71, 0.71, 0.61, 1.07, 0.85, 0.79, 0.64, 0.45, 0.53)

    def test_median_of_a_high_bias_install_sits_inside_the_limits(self):
        records = [{"forecast": 20.0, "actual": 20.0 * ratio} for ratio in self.RATIOS]
        factor = forecast_correction_factor(records)
        assert factor == pytest.approx(0.70)
        assert CHARGE_FORECAST_CORRECTION_MIN < factor < CHARGE_FORECAST_CORRECTION_MAX


class TestChargeScenarios:
    """19 kWh battery with realistic Irish daily loads and forecasts of 5, 14 and 25 kWh."""

    FORECASTS = (5.0, 14.0, 25.0)

    @pytest.mark.parametrize("load", [15.0, 20.0, 25.0])
    @pytest.mark.parametrize("min_soc", [10, 20])
    @pytest.mark.parametrize("profile", [None, "evening", "morning"])
    def test_target_monotone_in_forecast_and_within_limits(self, load, min_soc, profile):
        load_profile = {"evening": _evening_heavy(), "morning": _morning_heavy(), None: None}[
            profile
        ]
        targets = [
            _decide(
                forecast_kwh=f,
                average_daily_consumption_kwh=load,
                min_soc=min_soc,
                load_profile=load_profile,
            ).target_soc
            for f in self.FORECASTS
        ]
        assert targets[0] >= targets[1] >= targets[2]
        for t in targets:
            assert min_soc + 5 <= t <= 100

    @pytest.mark.parametrize("factor", [0.6, 0.85, 1.0, 1.2])
    def test_monotone_with_forecast_correction(self, factor):
        targets = [
            _decide(forecast_kwh=f, forecast_correction=factor).target_soc for f in self.FORECASTS
        ]
        assert targets[0] >= targets[1] >= targets[2]

    def test_low_forecast_charges_close_to_full_and_high_forecast_much_less(self):
        low = _decide(forecast_kwh=5.0, average_daily_consumption_kwh=25.0).target_soc
        high = _decide(forecast_kwh=25.0, average_daily_consumption_kwh=15.0).target_soc
        assert low >= 90
        assert high <= 40
