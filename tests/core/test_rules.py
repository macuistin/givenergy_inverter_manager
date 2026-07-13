"""Unit tests for the optimizer module."""

from datetime import datetime

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


class TestStorageHeater:
    """should_run_storage_heater in rules.py."""

    def _call(self, **overrides):
        from custom_components.givenergy_inverter_manager.core.rules import (
            should_run_storage_heater,
        )

        defaults = {
            "battery_soc": 85.0,
            "is_cheapest_rate": True,
            "solar_power_w": 0.0,
            "house_load_w": 500.0,
            "battery_power_w": 0.0,
            "heater_wattage_w": 3000.0,
            "heater_min_soc_cheap": 80,
        }
        defaults.update(overrides)
        return should_run_storage_heater(**defaults)

    def test_runs_during_cheap_rate_with_sufficient_soc(self):
        should, reason = self._call()
        assert should is True
        assert "cheap rate" in reason.lower()

    def test_does_not_run_during_cheap_rate_with_low_soc(self):
        should, reason = self._call(battery_soc=70.0, heater_min_soc_cheap=80)
        assert should is False
        assert "minimum" in reason.lower() or "below" in reason.lower()

    def test_runs_from_solar_surplus_outside_cheap_rate(self):
        should, reason = self._call(
            is_cheapest_rate=False,
            solar_power_w=5000.0,
            house_load_w=500.0,
            battery_soc=85.0,
        )
        assert should is True
        assert "solar" in reason.lower()

    def test_does_not_run_outside_cheap_rate_insufficient_surplus(self):
        should, reason = self._call(
            is_cheapest_rate=False,
            solar_power_w=2000.0,
            house_load_w=500.0,
            heater_wattage_w=3000.0,
            battery_soc=85.0,
        )
        assert should is False

    def test_does_not_run_outside_cheap_rate_low_battery(self):
        should, reason = self._call(
            is_cheapest_rate=False,
            solar_power_w=5000.0,
            house_load_w=500.0,
            battery_soc=60.0,
        )
        assert should is False
