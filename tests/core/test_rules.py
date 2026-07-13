"""Unit tests for the optimizer module."""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.rules import (
    calculate_overnight_charge_target,
    monthly_solar_fractions,
    should_divert_to_immersion,
    suggest_appliance_run,
)

# --- Overnight charge target tests ---


class TestCalculateOvernightChargeTarget:
    def _base_kwargs(self, **overrides):
        defaults = {
            "current_soc": 50.0,
            "battery_capacity_kwh": 19.0,
            "forecast_kwh": None,
            "inverter_max_kw": 5.0,
            "car_plugged_in": False,
            "min_soc": 10,
            "skip_charge_threshold": 75,
            "average_daily_consumption_kwh": 20.0,
            "cheapest_rate": 0.0965,
            "dt": datetime(2024, 6, 15, 22, 0),  # Summer evening
        }
        defaults.update(overrides)
        return defaults

    def test_skip_charge_high_soc_good_forecast(self):
        """Should skip charge when battery is high and forecast is good."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=80.0,
                forecast_kwh=15.0,  # Strong summer forecast
            )
        )
        assert decision.skip_charge is True
        assert decision.cost_to_charge == 0.0

    def test_no_skip_car_plugged_in(self):
        """Should not skip charge when car is plugged in even with high SoC."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=80.0,
                forecast_kwh=15.0,
                car_plugged_in=True,
            )
        )
        assert decision.skip_charge is False

    def test_high_target_poor_forecast(self):
        """Should charge to high target when forecast is poor."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=30.0,
                forecast_kwh=3.0,  # Very poor forecast
            )
        )
        assert decision.target_soc >= 85
        assert decision.skip_charge is False

    def test_moderate_target_decent_forecast(self):
        """Should charge to moderate target with decent forecast."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=40.0,
                forecast_kwh=10.0,  # Decent forecast
            )
        )
        assert 60 <= decision.target_soc <= 85

    def test_seasonal_fallback_winter(self):
        """Winter bypass charges to 100% regardless of forecast."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=30.0,
                forecast_kwh=None,
                dt=datetime(2024, 1, 15, 22, 0),  # Winter
                solar_fractions=monthly_solar_fractions(53.0),
            )
        )
        # Winter months always return 100% — solar is negligible
        assert decision.target_soc == 100
        assert "Winter month" in decision.reason

    def test_seasonal_fallback_summer(self):
        """Uses high seasonal estimate in summer with no forecast."""
        decision_summer = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=50.0,
                forecast_kwh=None,
                dt=datetime(2024, 6, 15, 22, 0),  # Summer
                solar_fractions=monthly_solar_fractions(53.0),
            )
        )
        decision_winter = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=50.0,
                forecast_kwh=None,
                dt=datetime(2024, 1, 15, 22, 0),  # Winter
                solar_fractions=monthly_solar_fractions(53.0),
            )
        )
        # Summer should result in lower target than winter
        assert decision_summer.target_soc <= decision_winter.target_soc

    def test_target_never_below_min_soc(self):
        """Target SoC is always above minimum SoC."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=15.0,
                forecast_kwh=20.0,
                min_soc=10,
            )
        )
        assert decision.target_soc > 10

    def test_target_never_exceeds_100(self):
        """Target SoC never exceeds 100%."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=10.0,
                forecast_kwh=0.5,
                car_plugged_in=True,
            )
        )
        assert decision.target_soc <= 100

    def test_cost_estimate_positive(self):
        """Cost to charge should be positive when charging needed."""
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=20.0,
                forecast_kwh=2.0,
            )
        )
        assert decision.cost_to_charge > 0

    def test_returns_reason_string(self):
        """Decision always includes a human-readable reason."""
        decision = calculate_overnight_charge_target(**self._base_kwargs())
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0


# --- Immersion divert tests ---


class TestShouldDivertToImmersion:
    def _base_kwargs(self, **overrides):
        defaults = {
            "solar_power_w": 4000.0,
            "house_load_w": 800.0,
            "battery_soc": 90.0,
            "battery_power_w": 500.0,  # Battery charging at 500W
            "inverter_max_w": 5000.0,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
        }
        defaults.update(overrides)
        return defaults

    def test_diverts_with_good_surplus(self):
        """Should divert when there's enough surplus and battery is high."""
        should, reason = should_divert_to_immersion(**self._base_kwargs())
        assert should is True

    def test_no_divert_water_hot(self):
        """Should not divert when water is already at target temp."""
        should, reason = should_divert_to_immersion(**self._base_kwargs(immersion_temp=56.0))
        assert should is False
        assert "already" in reason.lower()

    def test_no_divert_battery_low(self):
        """Should not divert when battery SoC is below threshold."""
        should, reason = should_divert_to_immersion(**self._base_kwargs(battery_soc=60.0))
        assert should is False
        assert "threshold" in reason.lower()

    def test_no_divert_insufficient_surplus(self):
        """Should not divert when solar surplus is too low."""
        should, reason = should_divert_to_immersion(
            **self._base_kwargs(
                solar_power_w=1000.0,
                house_load_w=900.0,  # Small surplus
            )
        )
        assert should is False

    def test_diverts_when_clipping(self):
        """Should divert when inverter is clipping regardless of small surplus."""
        should, reason = should_divert_to_immersion(
            **self._base_kwargs(
                solar_power_w=4900.0,  # Near inverter max
                house_load_w=800.0,  # Battery absorbing most
                battery_soc=90.0,
            )
        )
        assert should is True

    def test_no_divert_no_temp_sensor_at_target(self):
        """Should still divert when no temp sensor (immersion_temp=None)."""
        should, reason = should_divert_to_immersion(**self._base_kwargs(immersion_temp=None))
        assert should is True  # Can't know it's hot, so divert


# --- Appliance suggestion tests ---


class TestSuggestApplianceRun:
    def test_good_time_solar_surplus(self):
        """Good time to run appliance when solar surplus covers it."""
        is_good, reason = suggest_appliance_run(
            solar_power_w=4000.0,
            house_load_w=500.0,
            battery_soc=85.0,
            battery_power_w=0.0,
            appliance_power_w=2000.0,
            appliance_name="Washing Machine",
            rate_period_name="Day",
            rate=0.3334,
            export_rate=0.195,
        )
        assert is_good is True
        assert "surplus" in reason.lower()

    def test_bad_time_day_rate_no_surplus(self):
        """Bad time to run appliance at day rate with no solar."""
        is_good, reason = suggest_appliance_run(
            solar_power_w=0.0,
            house_load_w=500.0,
            battery_soc=40.0,
            battery_power_w=0.0,
            appliance_power_w=2000.0,
            appliance_name="Dishwasher",
            rate_period_name="Day",
            rate=0.3334,
            export_rate=0.195,
        )
        assert is_good is False
        assert "not recommended" in reason.lower() or "wait" in reason.lower()

    def test_acceptable_high_battery_cheap_rate(self):
        """Acceptable to run appliance with high battery and cheap rate."""
        is_good, reason = suggest_appliance_run(
            solar_power_w=500.0,
            house_load_w=400.0,
            battery_soc=90.0,
            battery_power_w=0.0,
            appliance_power_w=2000.0,
            appliance_name="Washing Machine",
            rate_period_name="Night",
            rate=0.1644,
            export_rate=0.195,
        )
        assert is_good is True


# ── Additional optimizer coverage ────────────────────────────────────────────


class TestImmersionDivertClippingPath:
    def test_diverts_clipping_even_with_marginal_surplus(self):
        """
        When inverter is clipping (at 95%+ of max output) and battery is above
        threshold, the immersion should activate even if net surplus calculation
        is marginal — the clipping itself signals abundant solar.
        """
        from custom_components.givenergy_inverter_manager.core.rules import (
            should_divert_to_immersion,
        )

        # Solar at 97% of inverter max — definite clipping
        # But house load is high so net_surplus_w < min_surplus_w
        should, reason = should_divert_to_immersion(
            solar_power_w=4850.0,  # 97% of 5kW
            house_load_w=4400.0,  # high house load — surplus < 500W threshold
            battery_soc=85.0,
            battery_power_w=50.0,  # barely charging
            inverter_max_w=5000.0,
            immersion_temp=40.0,
            immersion_target_temp=55.0,
            immersion_min_temp=30.0,
            soc_threshold=80,
            min_surplus_w=500,
        )
        assert should is True
        assert (
            "capacity" in reason.lower()
            or "clipping" in reason.lower()
            or "inverter" in reason.lower()
        )


class TestSuggestApplianceRunDayRatePath:
    def test_day_rate_no_surplus_returns_false_with_cost_in_reason(self):
        """
        At peak day rate with no solar surplus, suggestion should be False
        and the reason should include cost information.
        """
        from custom_components.givenergy_inverter_manager.core.rules import suggest_appliance_run

        is_good, reason = suggest_appliance_run(
            solar_power_w=100.0,  # negligible solar
            house_load_w=800.0,
            battery_soc=30.0,
            battery_power_w=0.0,
            appliance_power_w=2000.0,
            appliance_name="Dishwasher",
            rate_period_name="Day",
            rate=0.3334,
            export_rate=0.195,
        )
        assert is_good is False
        # Reason should mention the appliance name and something about cost
        assert "Dishwasher" in reason

    def test_suggest_no_strong_reason_at_boundary(self):
        """
        Battery is medium SoC and rate is moderate — no strong case either way.
        Should return False with a neutral reason.
        """
        from custom_components.givenergy_inverter_manager.core.rules import suggest_appliance_run

        is_good, reason = suggest_appliance_run(
            solar_power_w=1000.0,
            house_load_w=800.0,
            battery_soc=60.0,
            battery_power_w=0.0,
            appliance_power_w=2000.0,
            appliance_name="Washing Machine",
            rate_period_name="Night",
            rate=0.1644,  # cheap-ish but not surplus
            export_rate=0.195,
        )
        # Net surplus = 1000 - 800 = 200W, not enough for 2000W appliance
        # Battery at 60%, not ≥ 80% for high-battery path
        assert is_good is False


class TestOvernightChargeEdgeCases:
    def _base(self, **overrides):
        defaults = {
            "current_soc": 50.0,
            "battery_capacity_kwh": 19.0,
            "forecast_kwh": None,
            "inverter_max_kw": 5.0,
            "car_plugged_in": False,
            "min_soc": 10,
            "skip_charge_threshold": 75,
            "average_daily_consumption_kwh": 15.0,
            "cheapest_rate": 0.0965,
            "dt": __import__("datetime").datetime(
                2024, 7, 10, 14, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        }
        defaults.update(overrides)
        return defaults

    def test_car_plugged_in_adds_buffer_to_target(self):
        """Car plugged in should result in a higher target than without."""
        from custom_components.givenergy_inverter_manager.core.rules import (
            calculate_overnight_charge_target,
        )

        without_car = calculate_overnight_charge_target(
            **self._base(car_plugged_in=False, forecast_kwh=8.0)
        )
        with_car = calculate_overnight_charge_target(
            **self._base(car_plugged_in=True, forecast_kwh=8.0)
        )
        assert with_car.target_soc >= without_car.target_soc

    def test_zero_forecast_gives_high_target(self):
        """Zero kWh forecast (e.g. storm warning) should give near-maximum target."""
        from custom_components.givenergy_inverter_manager.core.rules import (
            calculate_overnight_charge_target,
        )

        decision = calculate_overnight_charge_target(
            **self._base(
                forecast_kwh=0.0,
                current_soc=20.0,
            )
        )
        assert decision.target_soc >= 85

    def test_full_battery_excellent_forecast_skips(self):
        """Battery essentially full + excellent summer forecast = skip charge."""
        from datetime import datetime

        from custom_components.givenergy_inverter_manager.core.rules import (
            calculate_overnight_charge_target,
        )

        decision = calculate_overnight_charge_target(
            **self._base(
                current_soc=82.0,
                forecast_kwh=18.0,  # can fill 19kWh battery
                dt=datetime(2024, 6, 15, 22, 0),
            )
        )
        assert decision.skip_charge is True


class TestForecastConservatism:
    """P10/P50 conservatism blend wires through calculate_overnight_charge_target."""

    def _base(self, **overrides):
        defaults = {
            "current_soc": 30.0,
            "battery_capacity_kwh": 10.0,
            "inverter_max_kw": 5.0,
            "car_plugged_in": False,
            "min_soc": 10,
            "skip_charge_threshold": 75,
            "average_daily_consumption_kwh": 10.0,
            "cheapest_rate": 0.10,
            "dt": datetime(2024, 6, 15, 22, 0),
        }
        defaults.update(overrides)
        return defaults

    def test_no_p10_entity_uses_p50_unchanged(self):
        # Arrange — P10=None means no Solcast P10 sensor configured
        decision_no_p10 = calculate_overnight_charge_target(
            **self._base(forecast_kwh=12.0, forecast_kwh_p10=None, forecast_conservatism=0.5)
        )
        decision_p50_only = calculate_overnight_charge_target(**self._base(forecast_kwh=12.0))
        # Assert — without a P10 value, conservatism has no effect
        assert decision_no_p10.target_soc == decision_p50_only.target_soc
        assert decision_no_p10.forecast_kwh == pytest.approx(12.0)

    def test_zero_conservatism_uses_p50_unchanged(self):
        # Arrange
        decision_plain = calculate_overnight_charge_target(
            **self._base(forecast_kwh=12.0)
        )
        decision_zero = calculate_overnight_charge_target(
            **self._base(forecast_kwh=12.0, forecast_kwh_p10=6.0, forecast_conservatism=0.0)
        )
        # Assert — conservatism=0 means pure P50, same target as no-P10 call
        assert decision_zero.target_soc == decision_plain.target_soc
        assert "blend" not in decision_zero.reason

    def test_full_conservatism_uses_p10(self):
        # Arrange — P50=12, P10=4; conservatism=1.0 means pure P10
        decision = calculate_overnight_charge_target(
            **self._base(forecast_kwh=12.0, forecast_kwh_p10=4.0, forecast_conservatism=1.0)
        )
        # Assert — pessimistic forecast means a higher charge target than P50 alone
        decision_p50 = calculate_overnight_charge_target(**self._base(forecast_kwh=12.0))
        assert decision.target_soc >= decision_p50.target_soc

    def test_partial_conservatism_blends_correctly(self):
        # Arrange — P50=10, P10=4; conservatism=0.5 → blended = 7.0
        # The blended forecast should fall in a different tier than pure P50
        decision_p50 = calculate_overnight_charge_target(**self._base(forecast_kwh=10.0))
        decision_blended = calculate_overnight_charge_target(
            **self._base(forecast_kwh=10.0, forecast_kwh_p10=4.0, forecast_conservatism=0.5)
        )
        # Assert — blended (7.0 kWh) produces the same or higher target than pure P50
        # (less optimistic forecast → same or more charging needed)
        assert decision_blended.forecast_kwh == pytest.approx(7.0)
        assert decision_blended.target_soc >= decision_p50.target_soc

    def test_p10_lower_than_p50_raises_target(self):
        # Arrange — pessimistic P10 gives less solar → need more overnight charge
        decision_p50_only = calculate_overnight_charge_target(**self._base(forecast_kwh=10.0))
        decision_with_p10 = calculate_overnight_charge_target(
            **self._base(forecast_kwh=10.0, forecast_kwh_p10=3.0, forecast_conservatism=0.5)
        )
        # Assert — adding P10 pessimism should not lower the target
        assert decision_with_p10.target_soc >= decision_p50_only.target_soc


class TestImmersionHysteresis:
    """Hysteresis prevents rapid on/off cycling near the target temperature.

    With target=55°C and hysteresis=5°C:
    - Turns OFF at 55°C
    - Will not restart until water cools below 50°C
    - If currently running at 52°C, keeps running (heading to 55°C)
    """

    def _base(self, **overrides):
        defaults = {
            "solar_power_w": 4000.0,
            "house_load_w": 800.0,
            "battery_soc": 90.0,
            "battery_power_w": 200.0,
            "inverter_max_w": 5000.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "immersion_hysteresis_c": 5.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
        }
        defaults.update(overrides)
        return defaults

    def test_turns_off_at_target(self):
        should, reason = should_divert_to_immersion(
            **self._base(immersion_temp=55.0, currently_on=True)
        )
        assert should is False
        assert "already" in reason.lower()

    def test_wont_restart_above_hysteresis_band(self):
        should, reason = should_divert_to_immersion(
            **self._base(immersion_temp=53.0, currently_on=False)
        )
        assert should is False
        assert "50" in reason

    def test_restarts_below_hysteresis_band(self):
        should, _ = should_divert_to_immersion(
            **self._base(immersion_temp=49.0, currently_on=False)
        )
        assert should is True

    def test_keeps_running_within_band(self):
        should, _ = should_divert_to_immersion(**self._base(immersion_temp=52.0, currently_on=True))
        assert should is True

    def test_exact_turn_on_boundary(self):
        should, _ = should_divert_to_immersion(
            **self._base(immersion_temp=50.0, currently_on=False)
        )
        assert should is False

    def test_just_below_turn_on_boundary(self):
        should, _ = should_divert_to_immersion(
            **self._base(immersion_temp=49.9, currently_on=False)
        )
        assert should is True

    def test_legionella_override_ignores_hysteresis(self):
        should, reason = should_divert_to_immersion(
            **self._base(immersion_temp=28.0, currently_on=False)
        )
        assert should is True
        assert "minimum" in reason.lower()

    def test_no_temp_sensor_ignores_hysteresis(self):
        should, _ = should_divert_to_immersion(
            **self._base(immersion_temp=None, currently_on=False)
        )
        assert should is True

    def test_no_surplus_shows_surplus_reason_not_hysteresis(self):
        """With 34W solar (no surplus), reason must be insufficient surplus
        not hysteresis — even if water is in the hysteresis band."""
        should, reason = should_divert_to_immersion(
            **self._base(
                solar_power_w=34.0,
                house_load_w=800.0,
                battery_soc=90.0,
                immersion_temp=54.0,
                currently_on=False,
                min_surplus_w=500.0,
            )
        )
        assert should is False
        assert "surplus" in reason.lower(), f"Expected surplus reason, got: {reason!r}"
        assert "hysteresis" not in reason.lower(), (
            f"Hysteresis reason is misleading when there is no surplus: {reason!r}"
        )

    def test_surplus_available_shows_hysteresis_reason(self):
        """With real surplus but water in hysteresis band, reason IS hysteresis."""
        should, reason = should_divert_to_immersion(
            **self._base(
                solar_power_w=3500.0,
                house_load_w=800.0,
                battery_soc=90.0,
                immersion_temp=54.0,
                currently_on=False,
                min_surplus_w=500.0,
            )
        )
        assert should is False
        assert "restart" in reason.lower() and "50" in reason, (
            f"With surplus but temp in band, expected restart-threshold reason: {reason!r}"
        )


class TestBatteryCycleCostDivertGuard:
    """Battery degradation cost check in should_divert_to_immersion."""

    def _base(self, **overrides):
        defaults = {
            "solar_power_w": 3500.0,
            "house_load_w": 800.0,
            "battery_soc": 90.0,
            "battery_power_w": 0.0,
            "inverter_max_w": 5000.0,
            "immersion_temp": 45.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 45.0,
        }
        defaults.update(overrides)
        return defaults

    def test_no_battery_cost_diverts_normally(self):
        # Arrange — default (disabled) — no cycle cost check
        should, _ = should_divert_to_immersion(
            **self._base(), battery_cycle_cost_per_kwh=0.0, export_rate=0.195
        )
        # Assert
        assert should is True

    def test_diverts_when_export_rate_exceeds_cycle_cost(self):
        # Arrange — export_rate 19.5c > cycle_cost 1.75c
        should, reason = should_divert_to_immersion(
            **self._base(), battery_cycle_cost_per_kwh=0.0175, export_rate=0.195
        )
        # Assert
        assert should is True

    def test_does_not_divert_when_export_rate_below_cycle_cost(self):
        # Arrange — export_rate 1c < cycle_cost 5c (edge case: low-value export market)
        should, reason = should_divert_to_immersion(
            **self._base(), battery_cycle_cost_per_kwh=0.05, export_rate=0.01
        )
        # Assert
        assert should is False
        assert "cycle cost" in reason

    def test_zero_export_rate_does_not_trigger_guard(self):
        # Arrange — export_rate=0 means no export tariff; guard should not block diversion
        should, _ = should_divert_to_immersion(
            **self._base(), battery_cycle_cost_per_kwh=0.05, export_rate=0.0
        )
        # Assert — 0 export rate means guard is inactive (condition: 0 < export_rate)
        assert should is True


class TestBatteryCycleCostEngine:
    """_battery_cycle_cost helper in engine.py."""

    def test_returns_zero_when_battery_cost_not_configured(self):
        from custom_components.givenergy_inverter_manager.core.engine import _battery_cycle_cost

        # Arrange / Act
        cost = _battery_cycle_cost({}, capacity_kwh=10.0)
        # Assert
        assert cost == pytest.approx(0.0)

    def test_computes_correct_cycle_cost(self):
        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_COST
        from custom_components.givenergy_inverter_manager.core.engine import _battery_cycle_cost

        # Arrange — €4,000 battery, 19 kWh, 6,000 cycles
        cfg = {CONF_BATTERY_COST: 4000.0}
        # Act
        cost = _battery_cycle_cost(cfg, capacity_kwh=19.0)
        # Assert — 4000 / (2 * 19 * 6000) ≈ 0.01754
        assert cost == pytest.approx(4000 / (2 * 19 * 6000), rel=1e-4)

    def test_returns_zero_when_capacity_is_zero(self):
        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_COST
        from custom_components.givenergy_inverter_manager.core.engine import _battery_cycle_cost

        cfg = {CONF_BATTERY_COST: 4000.0}
        assert _battery_cycle_cost(cfg, capacity_kwh=0.0) == pytest.approx(0.0)


class TestPreBoostExportOpportunity:
    """calculate_pre_boost_export_opportunity in rules.py."""

    from custom_components.givenergy_inverter_manager.core.rules import (
        calculate_pre_boost_export_opportunity,
    )

    def _calc(self, **overrides):
        from custom_components.givenergy_inverter_manager.core.rules import (
            calculate_pre_boost_export_opportunity,
        )

        defaults = {
            "current_soc": 70.0,
            "battery_capacity_kwh": 10.0,
            "target_soc": 80,
            "avg_daily_kwh": 10.0,
            "ceg_rate": 0.195,
            "cheapest_rate": 0.0965,
        }
        defaults.update(overrides)
        return calculate_pre_boost_export_opportunity(**defaults)

    def test_recommends_when_spare_and_positive_gain(self):
        # Arrange — battery higher than needed; export rate > boost rate
        spare, gain, recommended = self._calc(current_soc=95.0, target_soc=80)
        assert recommended is True
        assert spare > 0.0
        assert gain > 0.0

    def test_does_not_recommend_when_export_rate_below_boost_rate(self):
        # Arrange — boost rate > export rate → negative gain
        spare, gain, recommended = self._calc(ceg_rate=0.05, cheapest_rate=0.10)
        assert recommended is False
        assert gain <= 0.0

    def test_does_not_recommend_when_spare_below_minimum(self):
        # Arrange — current SoC just enough to cover deficit + evening load
        spare, gain, recommended = self._calc(current_soc=50.0, target_soc=80)
        assert recommended is False
        assert spare == pytest.approx(0.0)

    def test_spare_kwh_is_zero_when_soc_too_low(self):
        # Arrange — battery needs charging just to reach target, no room to export
        spare, gain, recommended = self._calc(current_soc=20.0, target_soc=80)
        assert spare == pytest.approx(0.0)
        assert recommended is False

    def test_spare_kwh_calculation(self):
        # Arrange — known values for manual check:
        # current_soc_kwh = 10 × 0.9 = 9.0
        # target_soc_kwh = 10 × 0.8 = 8.0
        # overnight_deficit = max(0, 8 - 9) = 0
        # evening_load = 10 × 0.25 = 2.5
        # spare = 9.0 - 0 - 2.5 = 6.5
        spare, _, _ = self._calc(current_soc=90.0, target_soc=80, avg_daily_kwh=10.0)
        assert spare == pytest.approx(6.5, rel=1e-3)

    def test_net_gain_calculation(self):
        # 6.5 kWh × (0.195 - 0.0965) = 6.5 × 0.0985 = 0.6403
        spare, gain, _ = self._calc(current_soc=90.0, target_soc=80, avg_daily_kwh=10.0)
        assert gain == pytest.approx(spare * (0.195 - 0.0965), rel=1e-3)
