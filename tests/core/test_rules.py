"""Unit tests for the optimizer module."""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.rules import monthly_solar_fractions
from tests.core.flat_rules import (
    available_surplus_w,
    calculate_overnight_charge_target,
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

    @pytest.mark.parametrize(("soc", "skip"), [(94.9, False), (95.0, True), (100.0, True)])
    def test_winter_charge_is_skipped_from_the_named_soc(self, soc, skip):
        from custom_components.givenergy_inverter_manager.const import CHARGE_WINTER_SKIP_SOC_PCT

        assert CHARGE_WINTER_SKIP_SOC_PCT == 95
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(current_soc=soc, dt=datetime(2024, 1, 15, 22, 0))
        )
        assert decision.skip_charge is skip

    def test_target_stays_the_named_headroom_above_min_soc(self):
        from custom_components.givenergy_inverter_manager.const import (
            CHARGE_MIN_TARGET_HEADROOM_PCT,
        )

        assert CHARGE_MIN_TARGET_HEADROOM_PCT == 5
        decision = calculate_overnight_charge_target(
            **self._base_kwargs(
                current_soc=100.0,
                forecast_kwh=60.0,
                average_daily_consumption_kwh=1.0,
                min_soc=40,
                skip_charge_threshold=101,
            )
        )
        assert decision.target_soc >= 40 + CHARGE_MIN_TARGET_HEADROOM_PCT

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


class TestShouldDivertToImmersionWithoutSwitch:
    """With no immersion switch there is nothing to drive, whatever the readings say."""

    def _kwargs(self, **overrides):
        defaults = {
            "solar_power_w": 4000.0,
            "house_load_w": 800.0,
            "battery_soc": 90.0,
            "battery_power_w": 500.0,
            "inverter_max_w": 5000.0,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
            "switch_configured": False,
        }
        defaults.update(overrides)
        return defaults

    def test_does_not_divert_with_a_large_surplus(self):
        should, reason = should_divert_to_immersion(**self._kwargs())
        assert should is False
        assert reason == "No immersion switch configured"

    def test_does_not_claim_to_heat_below_the_legionella_minimum(self):
        should, reason = should_divert_to_immersion(**self._kwargs(immersion_temp=20.0))
        assert should is False
        assert reason == "No immersion switch configured"

    def test_does_not_claim_to_divert_at_inverter_capacity(self):
        should, reason = should_divert_to_immersion(
            **self._kwargs(solar_power_w=5000.0, battery_soc=100.0)
        )
        assert should is False
        assert "diverting" not in reason

    def test_a_configured_switch_still_diverts_on_the_same_readings(self):
        should, _ = should_divert_to_immersion(**self._kwargs(switch_configured=True))
        assert should is True


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


class TestApplianceSuggestionMatchesSurplusHelper:
    """suggest_appliance_run uses available_surplus_w and the named appliance thresholds."""

    @staticmethod
    def _reference(solar, house, soc, battery_w, appliance_w, rate, export_rate):
        """The pre-refactor logic, with its inline constants."""
        net_surplus = solar - house - max(0, battery_w)
        if net_surplus >= appliance_w:
            return True, "surplus"
        if soc >= 80 and rate <= export_rate * 1.5:
            return True, "battery"
        if rate > export_rate * 1.5:
            return False, "expensive"
        return False, "no reason"

    @pytest.mark.parametrize("solar", [0.0, 1200.0, 3000.0, 5200.0])
    @pytest.mark.parametrize("house", [0.0, 400.0, 1500.0])
    @pytest.mark.parametrize("battery_w", [-1500.0, 0.0, 800.0])
    @pytest.mark.parametrize("soc", [10.0, 79.9, 80.0, 100.0])
    @pytest.mark.parametrize("rate", [0.1, 0.2925, 0.2926, 0.4])
    def test_same_verdict_as_inline_formula(self, solar, house, battery_w, soc, rate):
        export_rate = 0.195
        recommended, reason = suggest_appliance_run(
            solar_power_w=solar,
            house_load_w=house,
            battery_soc=soc,
            battery_power_w=battery_w,
            appliance_power_w=2000.0,
            appliance_name="Dishwasher",
            rate_period_name="Day",
            rate=rate,
            export_rate=export_rate,
        )
        expected, kind = self._reference(solar, house, soc, battery_w, 2000.0, rate, export_rate)
        assert recommended is expected
        markers = {
            "surplus": "surplus available",
            "battery": "Acceptable time",
            "expensive": "Not recommended",
            "no reason": "No strong reason",
        }
        assert markers[kind] in reason

    def test_thresholds_keep_their_values(self):
        from custom_components.givenergy_inverter_manager.const import (
            APPLIANCE_MIN_BATTERY_SOC,
            APPLIANCE_RATE_THRESHOLD,
        )

        assert APPLIANCE_MIN_BATTERY_SOC == 80
        assert APPLIANCE_RATE_THRESHOLD == 1.5


class TestImmersionDivertClippingPath:
    def test_diverts_clipping_even_with_marginal_surplus(self):
        """
        When inverter is clipping (at 95%+ of max output) and battery is above
        threshold, the immersion should activate even if net surplus calculation
        is marginal — the clipping itself signals abundant solar.
        """
        from tests.core.flat_rules import should_divert_to_immersion

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
        from tests.core.flat_rules import suggest_appliance_run

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
        from tests.core.flat_rules import suggest_appliance_run

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
        from tests.core.flat_rules import calculate_overnight_charge_target

        without_car = calculate_overnight_charge_target(
            **self._base(car_plugged_in=False, forecast_kwh=8.0)
        )
        with_car = calculate_overnight_charge_target(
            **self._base(car_plugged_in=True, forecast_kwh=8.0)
        )
        assert with_car.target_soc >= without_car.target_soc

    def test_zero_forecast_gives_high_target(self):
        """Zero kWh forecast (e.g. storm warning) should give near-maximum target."""
        from tests.core.flat_rules import calculate_overnight_charge_target

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

        from tests.core.flat_rules import calculate_overnight_charge_target

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


class TestForecastBlendWeightClamp:
    """The P10/P50 blend weight stays inside 0 to 1 for any conservatism value."""

    def _decide(self, conservatism):
        return calculate_overnight_charge_target(
            current_soc=50.0,
            battery_capacity_kwh=19.0,
            forecast_kwh=14.0,
            inverter_max_kw=5.0,
            car_plugged_in=False,
            min_soc=10,
            skip_charge_threshold=75,
            average_daily_consumption_kwh=20.0,
            cheapest_rate=0.0965,
            forecast_kwh_p10=6.0,
            forecast_conservatism=conservatism,
            dt=datetime(2026, 6, 15, 22, 0),
        )

    def test_negative_conservatism_behaves_as_zero(self):
        assert self._decide(-0.5).forecast_kwh == pytest.approx(14.0)

    def test_conservatism_above_one_behaves_as_one(self):
        assert self._decide(1.5).forecast_kwh == pytest.approx(6.0)

    @pytest.mark.parametrize("conservatism", [-1.0, -0.1, 0.0, 0.05, 0.5, 0.95, 1.0, 2.0])
    def test_blended_forecast_between_p10_and_p50(self, conservatism):
        assert 6.0 <= self._decide(conservatism).forecast_kwh <= 14.0


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


class TestForwardSocSimulation:
    """Forward SoC simulation helpers in rules.py."""

    def test_simulate_min_soc_decreases_with_low_solar(self):
        from tests.core.flat_rules import _simulate_min_soc

        # High load, zero solar → battery drains to 0
        min_soc = _simulate_min_soc(
            start_soc_pct=50.0,
            forecast_kwh=0.0,
            avg_daily_kwh=20.0,
            battery_capacity_kwh=10.0,
        )
        assert min_soc == pytest.approx(0.0)

    def test_simulate_min_soc_stays_above_zero_with_strong_solar(self):
        from tests.core.flat_rules import _simulate_min_soc

        # Even with strong solar, there's a morning trough before solar kicks in;
        # but the battery should stay above 0% (solar eventually refills it)
        min_soc = _simulate_min_soc(
            start_soc_pct=50.0,
            forecast_kwh=25.0,
            avg_daily_kwh=8.0,
            battery_capacity_kwh=10.0,
        )
        assert min_soc >= 20.0  # morning trough before solar kicks in

    def test_find_minimum_charge_target_high_solar(self):
        from tests.core.flat_rules import _find_minimum_charge_target

        # Strong solar → low target (solar will refill the battery)
        target = _find_minimum_charge_target(
            forecast_kwh=15.0,
            avg_daily_kwh=8.0,
            battery_capacity_kwh=10.0,
            min_soc=10,
        )
        assert target <= 50  # solar-rich day needs less overnight charge

    def test_find_minimum_charge_target_poor_solar(self):
        from tests.core.flat_rules import _find_minimum_charge_target

        # Poor solar → high target
        target = _find_minimum_charge_target(
            forecast_kwh=1.0,
            avg_daily_kwh=12.0,
            battery_capacity_kwh=10.0,
            min_soc=10,
        )
        assert target >= 80  # poor solar needs high overnight charge

    def test_find_minimum_charge_target_never_below_min_soc(self):
        from tests.core.flat_rules import _find_minimum_charge_target, _simulate_min_soc

        for forecast in [2.0, 5.0, 10.0, 15.0, 20.0]:
            target = _find_minimum_charge_target(
                forecast_kwh=forecast,
                avg_daily_kwh=10.0,
                battery_capacity_kwh=10.0,
                min_soc=10,
            )
            actual_min = _simulate_min_soc(target, forecast, 10.0, 10.0)
            assert actual_min >= 10 - 0.5, (
                f"forecast={forecast}: target={target}%, actual_min={actual_min:.1f}%"
            )

    def test_charge_target_monotone_with_forecast(self):
        from tests.core.flat_rules import _find_minimum_charge_target

        # More solar → lower or equal target
        prev = 100
        for forecast in [2.0, 5.0, 8.0, 12.0, 18.0, 25.0]:
            target = _find_minimum_charge_target(forecast, 10.0, 10.0, 10)
            assert target <= prev + 1, f"forecast={forecast}: target={target} > prev={prev}"
            prev = target

    def test_solar_slot_weights_sum_to_one(self):
        from custom_components.givenergy_inverter_manager.core.rules import _SOLAR_SLOT_WEIGHTS

        assert abs(sum(_SOLAR_SLOT_WEIGHTS) - 1.0) < 1e-9
        assert len(_SOLAR_SLOT_WEIGHTS) == 48

class TestOvermorrowCorrection:
    """Overmorrow correction in calculate_overnight_charge_target."""

    def _base(self, **overrides):
        defaults = {
            "current_soc": 50.0,
            "battery_capacity_kwh": 10.0,
            "forecast_kwh": 5.0,
            "inverter_max_kw": 5.0,
            "car_plugged_in": False,
            "min_soc": 10,
            "skip_charge_threshold": 75,
            "average_daily_consumption_kwh": 10.0,
            "cheapest_rate": 0.0965,
            "dt": datetime(2024, 6, 15, 22, 0),
        }
        defaults.update(overrides)
        return defaults

    def test_no_correction_without_d2(self):
        # Arrange — no day-2 forecast
        decision_no_d2 = calculate_overnight_charge_target(**self._base())
        decision_with_none = calculate_overnight_charge_target(
            **self._base(), forecast_kwh_d2=None
        )
        # Assert — both produce identical targets
        assert decision_no_d2.target_soc == decision_with_none.target_soc

    def test_correction_lowers_target_when_d2_overflows(self):
        # Arrange — day 2 has 20 kWh solar on a 10 kWh battery → 200% overflow
        decision_no_d2 = calculate_overnight_charge_target(**self._base())
        decision_with_d2 = calculate_overnight_charge_target(
            **self._base(), forecast_kwh_d2=20.0
        )
        # Assert — d+2 sunny → lower tonight's target
        assert decision_with_d2.target_soc < decision_no_d2.target_soc
        assert "Overmorrow" in decision_with_d2.reason

    def test_no_correction_when_d2_does_not_overflow(self):
        # Arrange — day 2 only 8 kWh on 10 kWh battery → no overflow
        decision_no_d2 = calculate_overnight_charge_target(**self._base())
        decision_weak_d2 = calculate_overnight_charge_target(
            **self._base(), forecast_kwh_d2=8.0
        )
        # Assert — d+2 not strong enough to trigger correction
        assert decision_weak_d2.target_soc == decision_no_d2.target_soc

    def test_no_correction_when_car_plugged_in(self):
        # Arrange — EV connected; correction disabled to protect EV buffer
        decision_no_ev = calculate_overnight_charge_target(
            **self._base(), forecast_kwh_d2=20.0
        )
        decision_with_ev = calculate_overnight_charge_target(
            **self._base(car_plugged_in=True), forecast_kwh_d2=20.0
        )
        # Assert — EV target >= non-EV target (correction doesn't lower EV target)
        assert decision_with_ev.target_soc >= decision_no_ev.target_soc

    def test_target_never_below_min_soc_plus_buffer(self):
        # Arrange — extreme d+2 (100 kWh) cannot reduce target below floor
        decision = calculate_overnight_charge_target(
            **self._base(), forecast_kwh_d2=100.0
        )
        # Assert — floor = min_soc (10%) applied via max(target_soc, min_soc + 5)
        assert decision.target_soc >= 15  # min_soc (10) + 5 guard


class TestAvailableSurplus:
    def test_off_subtracts_full_house_load(self):
        assert available_surplus_w(4000.0, 1000.0) == pytest.approx(3000.0)

    def test_on_adds_back_own_draw(self):
        assert available_surplus_w(4000.0, 4000.0, 0.0, True, 3000.0) == pytest.approx(3000.0)

    def test_same_surplus_off_and_on(self):
        off = available_surplus_w(4000.0, 1000.0, 200.0, False, 3000.0)
        on = available_surplus_w(4000.0, 4000.0, 200.0, True, 3000.0)
        assert off == pytest.approx(on)

    def test_off_ignores_element_wattage(self):
        assert available_surplus_w(4000.0, 1000.0, 0.0, False, 3000.0) == pytest.approx(3000.0)

    def test_add_back_capped_at_house_load(self):
        assert available_surplus_w(4000.0, 500.0, 0.0, True, 3000.0) == pytest.approx(4000.0)

    def test_battery_discharge_not_counted_as_surplus(self):
        assert available_surplus_w(2000.0, 1000.0, -800.0) == pytest.approx(1000.0)


class TestImmersionSurplusStability:
    """Turning the element on must not change the decision on the next cycle."""

    def _kwargs(self, **overrides):
        defaults = {
            "battery_soc": 90.0,
            "battery_power_w": 0.0,
            "inverter_max_w": 8000.0,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
            "immersion_power_w": 3000.0,
        }
        defaults.update(overrides)
        return defaults

    def test_stays_on_after_element_draw_appears_in_house_load(self):
        off, _ = should_divert_to_immersion(
            solar_power_w=4000.0, house_load_w=1000.0, currently_on=False, **self._kwargs()
        )
        on, reason = should_divert_to_immersion(
            solar_power_w=4000.0, house_load_w=4000.0, currently_on=True, **self._kwargs()
        )
        assert off is True
        assert on is True, reason

    def test_reason_reports_same_surplus_before_and_after(self):
        _, off_reason = should_divert_to_immersion(
            solar_power_w=4000.0, house_load_w=1000.0, currently_on=False, **self._kwargs()
        )
        _, on_reason = should_divert_to_immersion(
            solar_power_w=4000.0, house_load_w=4000.0, currently_on=True, **self._kwargs()
        )
        assert "3000W" in off_reason
        assert "3000W" in on_reason

    def test_old_behaviour_without_element_wattage_unchanged(self):
        should, _ = should_divert_to_immersion(
            solar_power_w=4000.0,
            house_load_w=4000.0,
            currently_on=False,
            **self._kwargs(immersion_power_w=0.0),
        )
        assert should is False


class TestImmersionStartStopBand:
    def _kwargs(self, **overrides):
        defaults = {
            "battery_soc": 90.0,
            "battery_power_w": 0.0,
            "inverter_max_w": 8000.0,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
            "immersion_power_w": 3000.0,
        }
        defaults.update(overrides)
        return defaults

    def test_does_not_start_below_min_surplus(self):
        should, _ = should_divert_to_immersion(
            solar_power_w=1400.0, house_load_w=1000.0, currently_on=False, **self._kwargs()
        )
        assert should is False

    def test_starts_at_min_surplus(self):
        should, _ = should_divert_to_immersion(
            solar_power_w=1500.0, house_load_w=1000.0, currently_on=False, **self._kwargs()
        )
        assert should is True

    def test_stays_on_with_small_deficit(self):
        # rest of house 1000 W, solar 800 W: surplus -200 W, inside the -500 W band
        should, reason = should_divert_to_immersion(
            solar_power_w=800.0, house_load_w=4000.0, currently_on=True, **self._kwargs()
        )
        assert should is True, reason

    def test_stays_on_at_band_edge(self):
        should, _ = should_divert_to_immersion(
            solar_power_w=500.0, house_load_w=4000.0, currently_on=True, **self._kwargs()
        )
        assert should is True

    def test_stops_below_band(self):
        should, reason = should_divert_to_immersion(
            solar_power_w=400.0, house_load_w=4000.0, currently_on=True, **self._kwargs()
        )
        assert should is False
        assert "insufficient" in reason.lower()

    def test_band_follows_configured_min_surplus(self):
        should, _ = should_divert_to_immersion(
            solar_power_w=0.0,
            house_load_w=4000.0,
            currently_on=True,
            **self._kwargs(min_surplus_w=1200),
        )
        assert should is True


class TestImmersionSensorDropouts:
    def _kwargs(self, **overrides):
        defaults = {
            "solar_power_w": 4000.0,
            "house_load_w": 800.0,
            "battery_soc": 90.0,
            "battery_power_w": 0.0,
            "inverter_max_w": 8000.0,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "soc_threshold": 80,
            "min_surplus_w": 500,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.parametrize("name", ["solar_power_w", "house_load_w", "battery_power_w"])
    def test_does_not_start_on_missing_input(self, name):
        should, reason = should_divert_to_immersion(**self._kwargs(**{name: None}))
        assert should is False
        assert "sensor unavailable" in reason.lower()

    @pytest.mark.parametrize("name", ["solar_power_w", "house_load_w", "battery_power_w"])
    def test_holds_on_when_input_missing(self, name):
        should, reason = should_divert_to_immersion(
            **self._kwargs(**{name: None}), currently_on=True
        )
        assert should is True
        assert "sensor unavailable" in reason.lower()

    def test_does_not_start_on_unavailable_temp(self):
        should, reason = should_divert_to_immersion(
            **self._kwargs(immersion_temp=None), immersion_temp_unavailable=True
        )
        assert should is False
        assert "immersion_temp" in reason

    def test_holds_on_when_temp_unavailable(self):
        should, _ = should_divert_to_immersion(
            **self._kwargs(immersion_temp=None),
            immersion_temp_unavailable=True,
            currently_on=True,
        )
        assert should is True

    def test_no_temp_sensor_configured_is_not_a_dropout(self):
        should, _ = should_divert_to_immersion(**self._kwargs(immersion_temp=None))
        assert should is True

    def test_reason_names_every_missing_input(self):
        _, reason = should_divert_to_immersion(
            **self._kwargs(house_load_w=None, battery_power_w=None)
        )
        assert "house_load" in reason
        assert "battery_power" in reason

    def test_legionella_heating_does_not_need_load_sensors(self):
        should, reason = should_divert_to_immersion(
            **self._kwargs(immersion_temp=20.0, house_load_w=None, battery_power_w=None)
        )
        assert should is True
        assert "minimum safe" in reason

    def test_target_reached_still_turns_off_when_load_missing(self):
        should, _ = should_divert_to_immersion(
            **self._kwargs(immersion_temp=56.0, house_load_w=None), currently_on=True
        )
        assert should is False

    @pytest.mark.parametrize("name", ["solar_power_w", "house_load_w", "battery_power_w"])
    def test_turns_off_once_outage_reaches_hold_limit(self, name):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MIN_WRITE_INTERVAL_S,
        )

        should, reason = should_divert_to_immersion(
            **self._kwargs(**{name: None}),
            currently_on=True,
            unavailable_for_s=GIVTCP_MIN_WRITE_INTERVAL_S,
        )
        assert should is False
        assert "turning off" in reason

    def test_hold_limit_is_its_own_setting_of_five_minutes(self):
        from custom_components.givenergy_inverter_manager.const import SENSOR_OUTAGE_HOLD_LIMIT_S

        assert SENSOR_OUTAGE_HOLD_LIMIT_S == 300

    def test_holds_on_just_under_hold_limit(self):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MIN_WRITE_INTERVAL_S,
        )

        should, _ = should_divert_to_immersion(
            **self._kwargs(house_load_w=None),
            currently_on=True,
            unavailable_for_s=GIVTCP_MIN_WRITE_INTERVAL_S - 1,
        )
        assert should is True

    def test_turns_off_after_hold_limit_when_temp_unavailable(self):
        should, _ = should_divert_to_immersion(
            **self._kwargs(immersion_temp=None),
            immersion_temp_unavailable=True,
            currently_on=True,
            unavailable_for_s=3600.0,
        )
        assert should is False

    def test_legionella_heating_wins_over_expired_hold(self):
        should, reason = should_divert_to_immersion(
            **self._kwargs(immersion_temp=20.0, house_load_w=None),
            currently_on=True,
            unavailable_for_s=3600.0,
        )
        assert should is True
        assert "minimum safe" in reason
