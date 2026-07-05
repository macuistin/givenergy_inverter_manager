"""Unit tests for the battery module."""
from datetime import date

import pytest

from custom_components.givenergy_inverter_manager.core.battery import (
    TYPICAL_RATED_CYCLES,
    BatteryStats,
    calculate_cycle_increment,
    estimate_will_survive_night,
)


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
        """100% SoC change = 1.0 cycle."""
        assert calculate_cycle_increment(100.0) == pytest.approx(1.0)

    def test_half_cycle(self):
        """50% SoC change = 0.5 cycle."""
        assert calculate_cycle_increment(50.0) == pytest.approx(0.5)

    def test_zero_change(self):
        """0% SoC change = 0 cycles."""
        assert calculate_cycle_increment(0.0) == pytest.approx(0.0)

    def test_negative_delta_absolute(self):
        """Negative SoC delta (discharge) treated as absolute value."""
        assert calculate_cycle_increment(-50.0) == pytest.approx(0.5)


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
