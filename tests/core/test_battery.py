"""Unit tests for the battery module."""

from datetime import date, timedelta

import pytest

from custom_components.givenergy_inverter_manager.core.battery import (
    TYPICAL_RATED_CYCLES,
    BatteryStats,
    SurvivalReport,
    calculate_cycle_increment,
)
from tests.core.flat_battery import FROZEN_TODAY, estimate_will_survive_night, update_battery_stats

TODAY = FROZEN_TODAY


class TestBatteryStats:
    def test_remaining_life_new_battery(self):
        """New battery should show close to 100% remaining life."""
        stats = BatteryStats(total_cycles=0.0)
        assert stats.estimated_remaining_life_pct == pytest.approx(100.0)

    def test_remaining_life_half_used(self):
        """Half cycles used = ~50% remaining."""
        stats = BatteryStats(total_cycles=TYPICAL_RATED_CYCLES / 2)
        assert stats.estimated_remaining_life_pct == pytest.approx(50.0)

    def test_remaining_life_fully_used(self):
        """Fully cycled battery = 0% remaining."""
        stats = BatteryStats(total_cycles=TYPICAL_RATED_CYCLES)
        assert stats.estimated_remaining_life_pct == pytest.approx(0.0)

    def test_remaining_life_never_negative(self):
        """Remaining life never goes below 0."""
        stats = BatteryStats(total_cycles=TYPICAL_RATED_CYCLES * 2)
        assert stats.estimated_remaining_life_pct == pytest.approx(0.0)

    def test_days_since_full_charge(self):
        """Days since full charge calculated correctly."""
        stats = BatteryStats(last_full_charge_date=date(2026, 6, 1))
        assert stats.days_since_full_charge_on(TODAY) == 14
        assert stats.days_since_full_charge_on(date(2026, 6, 1)) == 0

    def test_days_since_full_charge_property_counts_to_the_wall_clock_date(self):
        stats = BatteryStats(last_full_charge_date=date.today() - timedelta(days=3))
        assert stats.days_since_full_charge == 3

    def test_days_since_full_charge_none(self):
        """Returns None if never fully charged."""
        stats = BatteryStats(last_full_charge_date=None)
        assert stats.days_since_full_charge is None
        assert stats.days_since_full_charge_on(TODAY) is None

    def test_average_daily_cycles_empty(self):
        """Returns 0 if no cycle history."""
        stats = BatteryStats()
        assert stats.average_daily_cycles(TODAY) == 0.0

    def test_full_cycle(self):
        """A 100% fall in SoC = 1.0 cycle."""
        assert calculate_cycle_increment(-100.0) == pytest.approx(1.0)

    def test_half_cycle(self):
        """A 50% fall in SoC = 0.5 cycle."""
        assert calculate_cycle_increment(-50.0) == pytest.approx(0.5)

    def test_charging_adds_nothing(self):
        """A rising SoC is not an equivalent full cycle."""
        assert calculate_cycle_increment(50.0) == pytest.approx(0.0)
        assert calculate_cycle_increment(100.0) == pytest.approx(0.0)

    def test_zero_change(self):
        """0% SoC change = 0 cycles."""
        assert calculate_cycle_increment(0.0) == pytest.approx(0.0)

    def test_full_discharge_and_recharge_is_one_cycle(self):
        """Down 100 then up 100 is one equivalent full cycle, not two."""
        total = calculate_cycle_increment(-100.0) + calculate_cycle_increment(100.0)
        assert total == pytest.approx(1.0)


class TestWillSurviveNight:
    def test_survives_with_plenty(self):
        """Battery survives night with plenty of charge."""
        survives, soc_at_sunrise, reason = estimate_will_survive_night(
            current_soc=80.0,
            battery_capacity_kwh=19.0,
            min_soc=10.0,
            hours_until_solar=8.0,
            average_hourly_consumption_kwh=0.8,
        )
        assert survives is True
        assert soc_at_sunrise > 10.0

    def test_does_not_survive_low_soc(self):
        """Battery runs out before morning when SoC is low."""
        survives, soc_at_sunrise, reason = estimate_will_survive_night(
            current_soc=15.0,
            battery_capacity_kwh=19.0,
            min_soc=10.0,
            hours_until_solar=8.0,
            average_hourly_consumption_kwh=1.5,  # High consumption
        )
        assert survives is False
        assert "shortfall" in reason.lower()

    def test_soc_at_sunrise_never_below_min(self):
        """Estimated SoC at sunrise is always at least min SoC."""
        survives, soc_at_sunrise, reason = estimate_will_survive_night(
            current_soc=80.0,
            battery_capacity_kwh=19.0,
            min_soc=10.0,
            hours_until_solar=8.0,
            average_hourly_consumption_kwh=0.3,
        )
        assert soc_at_sunrise >= 10.0

    def test_reason_string_provided(self):
        """Always returns a reason string."""
        _, _, reason = estimate_will_survive_night(
            current_soc=50.0,
            battery_capacity_kwh=19.0,
            min_soc=10.0,
            hours_until_solar=8.0,
            average_hourly_consumption_kwh=0.5,
        )
        assert isinstance(reason, str)
        assert len(reason) > 0


# ── BatterySession coverage ───────────────────────────────────────────────────


class TestYearsRemainingEstimate:
    """years_remaining_estimate needs tracked days and a non-zero cycle rate."""

    @staticmethod
    def _stats(total, start_cycles, days_ago):
        return BatteryStats(
            total_cycles=total,
            tracking_start_date=TODAY - timedelta(days=days_ago),
            tracking_start_cycles=start_cycles,
        )

    def test_none_when_tracking_not_started(self):
        assert BatteryStats(total_cycles=100.0).years_remaining_estimate(TODAY) is None

    def test_none_before_minimum_days(self):
        assert self._stats(total=85.0, start_cycles=79.0, days_ago=6).years_remaining_estimate(TODAY) is None

    def test_none_when_no_new_cycles(self):
        assert self._stats(total=79.0, start_cycles=79.0, days_ago=30).years_remaining_estimate(TODAY) is None

    def test_average_ignores_cycles_before_tracking_started(self):
        stats = self._stats(total=179.0, start_cycles=79.0, days_ago=50)
        assert stats.average_daily_cycles(TODAY) == pytest.approx(2.0)

    def test_years_remaining_from_rate(self):
        stats = self._stats(total=179.0, start_cycles=79.0, days_ago=50)
        expected = (6000 - 179.0) / (2.0 * 365)
        assert stats.years_remaining_estimate(TODAY) == pytest.approx(expected)

    def test_first_soc_change_starts_tracking_at_current_total(self):
        stats = BatteryStats(total_cycles=79.0)
        update_battery_stats(stats, current_soc=40.0, last_soc=50.0)
        assert stats.tracking_start_cycles == pytest.approx(79.0)
        assert stats.tracking_start_date is not None
        assert stats.total_cycles == pytest.approx(79.1)


class TestLifetimeCyclesFromBms:
    """update_battery_stats prefers the BMS counter over the SoC estimate."""

    def test_bms_counter_sets_total_cycles(self):
        stats = BatteryStats()
        update_battery_stats(stats, 80.0, None, lifetime_cycles=38.0)
        assert stats.total_cycles == pytest.approx(38.0)
        assert stats.lifetime_from_bms is True

    def test_soc_movement_is_not_added_on_top_of_the_bms_counter(self):
        stats = BatteryStats()
        update_battery_stats(stats, 79.0, 80.0, lifetime_cycles=38.0)
        assert stats.total_cycles == pytest.approx(38.0)

    def test_bms_counter_starts_tracking_at_its_own_value(self):
        stats = BatteryStats()
        update_battery_stats(stats, 80.0, None, lifetime_cycles=38.0)
        assert stats.tracking_start_date is not None
        assert stats.tracking_start_cycles == pytest.approx(38.0)

    def test_switching_to_bms_keeps_the_daily_rate(self):
        stats = BatteryStats(
            total_cycles=10.0,
            tracking_start_date=TODAY - timedelta(days=10),
            tracking_start_cycles=0.0,
        )
        assert stats.average_daily_cycles(TODAY) == pytest.approx(1.0)
        update_battery_stats(stats, 80.0, None, lifetime_cycles=50.0)
        assert stats.total_cycles == pytest.approx(50.0)
        assert stats.average_daily_cycles(TODAY) == pytest.approx(1.0)

    def test_later_bms_growth_raises_the_daily_rate(self):
        stats = BatteryStats(
            total_cycles=10.0,
            tracking_start_date=TODAY - timedelta(days=10),
            tracking_start_cycles=0.0,
        )
        update_battery_stats(stats, 80.0, None, lifetime_cycles=50.0)
        update_battery_stats(stats, 80.0, 80.0, lifetime_cycles=55.0)
        assert stats.average_daily_cycles(TODAY) == pytest.approx(1.5)

    def test_zero_bms_counter_falls_back_to_the_estimate(self):
        stats = BatteryStats(total_cycles=3.0)
        update_battery_stats(stats, 79.0, 80.0, lifetime_cycles=0.0)
        assert stats.total_cycles == pytest.approx(3.01)
        assert stats.lifetime_from_bms is False

    def test_estimate_continues_from_the_last_bms_value(self):
        stats = BatteryStats()
        update_battery_stats(stats, 80.0, None, lifetime_cycles=38.0)
        update_battery_stats(stats, 79.0, 80.0, lifetime_cycles=None)
        assert stats.total_cycles == pytest.approx(38.01)
        assert stats.lifetime_from_bms is False

    def test_remaining_life_and_years_use_the_bms_total(self):
        stats = BatteryStats(
            total_cycles=100.0,
            tracking_start_date=TODAY - timedelta(days=70),
            tracking_start_cycles=0.0,
        )
        update_battery_stats(stats, 80.0, None, lifetime_cycles=500.0)
        assert stats.estimated_remaining_life_pct == pytest.approx((1 - 500 / 6000) * 100)
        assert stats.years_remaining_estimate(TODAY) == pytest.approx((6000 - 500) / ((100 / 70) * 365))


class TestSurvivalAttributes:
    def _attrs(self, survive=True, sunrise=40.0, min_soc=10.0, now=60.0, reason="ok"):
        from custom_components.givenergy_inverter_manager.core.battery import (
            survival_attributes,
        )

        return survival_attributes(SurvivalReport(survive, sunrise, min_soc, now, reason))

    def test_critical_explains_with_the_shortfall(self):
        attrs = self._attrs(survive=False, sunrise=10.0, reason="Battery may run low. Shortfall 1.8kWh.")
        assert attrs["explanation"] == "Battery may run low. Shortfall 1.8kWh."

    def test_warning_says_it_lasts_but_only_just(self):
        attrs = self._attrs(sunrise=12.0)
        assert attrs["explanation"].startswith("The battery should last until solar starts")
        assert "about 12% at sunrise" in attrs["explanation"]
        assert "within 5 points of the 10% minimum" in attrs["explanation"]

    def test_warning_threshold_is_the_minimum_plus_the_margin(self):
        assert self._attrs(sunrise=14.9)["outlook"] == "Only just lasts the night"
        assert self._attrs(sunrise=15.0)["outlook"] == "Lasts the night"

    def test_safe_repeats_the_reason(self):
        attrs = self._attrs(sunrise=40.0, reason="Battery should last until solar.")
        assert attrs["explanation"] == "Battery should last until solar."

    def test_the_outlook_says_whether_the_battery_lasts_the_night_in_plain_words(self):
        assert self._attrs(sunrise=40.0)["outlook"] == "Lasts the night"
        assert self._attrs(sunrise=12.0)["outlook"] == "Only just lasts the night"
        assert self._attrs(survive=False, sunrise=10.0)["outlook"] == "May run low"

    def test_the_summary_adds_the_charge_expected_at_sunrise(self):
        assert self._attrs(sunrise=36.4)["summary"] == "Lasts the night · 36% at sunrise"
        assert self._attrs(sunrise=12.0)["summary"] == "Only just lasts the night · 12% at sunrise"

    def test_a_battery_that_runs_out_has_no_sunrise_figure_in_the_summary(self):
        assert self._attrs(survive=False, sunrise=10.0)["summary"] == "May run low"

    def test_no_phrase_says_survival(self):
        for attrs in (self._attrs(), self._attrs(sunrise=12.0), self._attrs(survive=False)):
            assert "surviv" not in (attrs["outlook"] + attrs["summary"]).lower()

    def test_numbers_are_included(self):
        attrs = self._attrs(sunrise=12.34, min_soc=10.0, now=61.26)
        assert attrs["estimated_soc_at_sunrise"] == 12.3
        assert attrs["battery_soc"] == 61.3
        assert attrs["minimum_soc"] == 10.0
        assert attrs["warning_below_soc"] == 15.0
