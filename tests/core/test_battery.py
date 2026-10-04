"""Unit tests for the battery module."""

from datetime import date

import pytest

from custom_components.givenergy_inverter_manager.core.battery import (
    TYPICAL_RATED_CYCLES,
    BatteryStats,
    calculate_cycle_increment,
    estimate_will_survive_night,
)
from custom_components.givenergy_inverter_manager.core.engine import update_battery_stats


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
        stats = BatteryStats(last_full_charge_date=date(2024, 6, 1))
        # This will vary by test run date, just check it's a non-negative int
        assert isinstance(stats.days_since_full_charge, int)
        assert stats.days_since_full_charge >= 0

    def test_days_since_full_charge_none(self):
        """Returns None if never fully charged."""
        stats = BatteryStats(last_full_charge_date=None)
        assert stats.days_since_full_charge is None

    def test_average_daily_cycles_empty(self):
        """Returns 0 if no cycle history."""
        stats = BatteryStats()
        assert stats.average_daily_cycles == 0.0

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
        from datetime import date, timedelta

        return BatteryStats(
            total_cycles=total,
            tracking_start_date=date.today() - timedelta(days=days_ago),
            tracking_start_cycles=start_cycles,
        )

    def test_none_when_tracking_not_started(self):
        assert BatteryStats(total_cycles=100.0).years_remaining_estimate is None

    def test_none_before_minimum_days(self):
        assert self._stats(total=85.0, start_cycles=79.0, days_ago=6).years_remaining_estimate is None

    def test_none_when_no_new_cycles(self):
        assert self._stats(total=79.0, start_cycles=79.0, days_ago=30).years_remaining_estimate is None

    def test_average_ignores_cycles_before_tracking_started(self):
        stats = self._stats(total=179.0, start_cycles=79.0, days_ago=50)
        assert stats.average_daily_cycles == pytest.approx(2.0)

    def test_years_remaining_from_rate(self):
        stats = self._stats(total=179.0, start_cycles=79.0, days_ago=50)
        expected = (6000 - 179.0) / (2.0 * 365)
        assert stats.years_remaining_estimate == pytest.approx(expected)

    def test_first_soc_change_starts_tracking_at_current_total(self):
        stats = BatteryStats(total_cycles=79.0)
        update_battery_stats(stats, current_soc=40.0, last_soc=50.0)
        assert stats.tracking_start_cycles == pytest.approx(79.0)
        assert stats.tracking_start_date is not None
        assert stats.total_cycles == pytest.approx(79.1)
