"""The winter and shoulder months: defaults by latitude, and what a saved list does."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_SHOULDER_MIN_SOC,
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
)
from custom_components.givenergy_inverter_manager.core.seasons import (
    NORTHERN_SEASONS,
    SeasonRules,
    default_months,
    overlapping_months,
    season_defaults,
    season_rules,
)


def _on(month: int) -> datetime:
    return datetime(2031, month, 15, 22, 0, tzinfo=timezone.utc)


def _inputs(seasons: SeasonRules = NORTHERN_SEASONS, **kw) -> ChargeInputs:
    values = {
        "current_soc": 40.0,
        "battery_capacity_kwh": 10.0,
        "min_soc": 10,
        "skip_charge_threshold": 75,
        "car_plugged_in": False,
        "inverter_max_kw": 5.0,
        "average_daily_consumption_kwh": 10.0,
        "cheapest_rate": 0.15,
        "seasons": seasons,
    }
    return ChargeInputs(**{**values, **kw})


FORECAST = SolarForecast(forecast_kwh=12.0)


class TestDefaults:
    @pytest.mark.parametrize("latitude", [53.3, 0.0, 0.0001, 70.0])
    def test_north_or_on_the_equator_are_the_northern_seasons(self, latitude):
        assert default_months(latitude) == ((12, 1, 2), (3, 4, 10, 11))

    @pytest.mark.parametrize("latitude", [-0.0001, -33.9, -45.0])
    def test_south_is_the_same_months_six_later(self, latitude):
        winter, shoulder = default_months(latitude)

        assert sorted(winter) == [6, 7, 8]
        assert sorted(shoulder) == [4, 5, 9, 10]

    def test_the_defaults_are_sorted_lists_as_the_configuration_holds_them(self):
        assert season_defaults(53.3) == {
            CONF_CHARGE_WINTER_MONTHS: [1, 2, 12],
            CONF_CHARGE_SHOULDER_MONTHS: [3, 4, 10, 11],
        }

    def test_the_northern_defaults_are_todays_constants(self):
        assert NORTHERN_SEASONS.winter_months == (12, 1, 2)
        assert NORTHERN_SEASONS.shoulder_months == (3, 4, 10, 11)
        assert NORTHERN_SEASONS.winter_uses_forecast is False


class TestSeasonRules:
    def test_nothing_saved_gives_the_defaults_for_the_latitude(self):
        north = season_rules({}, 53.3)
        south = season_rules({}, -33.9)

        assert north == NORTHERN_SEASONS
        assert south.winter_months == (6, 7, 8)

    def test_a_saved_list_replaces_the_default(self):
        rules = season_rules({CONF_CHARGE_WINTER_MONTHS: [11, 12, 1, 2]}, 53.3)

        assert rules.winter_months == (1, 2, 11, 12)
        assert rules.shoulder_months == (3, 4, 10, 11)

    def test_an_empty_saved_list_turns_the_rule_off_and_is_not_the_default(self):
        rules = season_rules({CONF_CHARGE_WINTER_MONTHS: []}, 53.3)

        assert rules.winter_months == ()

    def test_entries_that_are_not_months_are_dropped(self):
        rules = season_rules({CONF_CHARGE_SHOULDER_MONTHS: ["3", 13, 0, "x", None, 4, 4]}, 53.3)

        assert rules.shoulder_months == (3, 4)

    def test_a_value_that_is_not_a_list_falls_back_to_the_default(self):
        assert season_rules({CONF_CHARGE_WINTER_MONTHS: "12"}, 53.3).winter_months == (12, 1, 2)

    def test_the_winter_behaviour_is_off_unless_saved(self):
        assert season_rules({}, 53.3).winter_uses_forecast is False
        assert season_rules({CONF_CHARGE_WINTER_USES_FORECAST: True}, 53.3).winter_uses_forecast


class TestOverlap:
    def test_a_month_in_both_lists_is_found(self):
        assert overlapping_months([12, 1], [1, 2]) == [1]

    def test_lists_that_do_not_meet_have_no_overlap(self):
        assert overlapping_months([12, 1, 2], [3, 4]) == []

    def test_missing_lists_have_no_overlap(self):
        assert overlapping_months(None, [3]) == []


class TestTheTargetUsesTheRules:
    def test_a_northern_winter_month_charges_to_100(self):
        decision = calculate_overnight_charge_target(_inputs(), FORECAST, _on(1))

        assert decision.target_soc == 100
        assert "Winter" in decision.reason

    def test_a_southern_winter_month_charges_to_100_and_a_northern_one_does_not(self):
        south = season_rules({}, -33.9)

        assert calculate_overnight_charge_target(_inputs(south), FORECAST, _on(7)).target_soc == 100
        assert calculate_overnight_charge_target(_inputs(south), FORECAST, _on(1)).target_soc < 100

    def test_a_custom_winter_list_is_used(self):
        rules = SeasonRules(winter_months=(11,), shoulder_months=())

        assert calculate_overnight_charge_target(_inputs(rules), FORECAST, _on(11)).target_soc == 100
        assert calculate_overnight_charge_target(_inputs(rules), FORECAST, _on(1)).target_soc < 100

    def test_empty_lists_turn_both_rules_off(self):
        rules = SeasonRules(winter_months=(), shoulder_months=())

        january = calculate_overnight_charge_target(_inputs(rules), FORECAST, _on(1))
        april = calculate_overnight_charge_target(_inputs(rules), FORECAST, _on(4))

        assert "Winter" not in january.reason
        assert january.target_soc < 100
        assert april.target_soc < 100

    def test_a_shoulder_month_raises_the_floor_and_summer_does_not(self):
        shoulder = calculate_overnight_charge_target(_inputs(), FORECAST, _on(4))
        summer = calculate_overnight_charge_target(_inputs(), FORECAST, _on(6))

        assert shoulder.target_soc >= CHARGE_SHOULDER_MIN_SOC
        assert summer.target_soc < shoulder.target_soc

    def test_a_southern_shoulder_month_raises_the_floor(self):
        south = season_rules({}, -33.9)

        april = calculate_overnight_charge_target(_inputs(south), FORECAST, _on(4))
        january = calculate_overnight_charge_target(_inputs(south), FORECAST, _on(1))

        assert april.target_soc >= CHARGE_SHOULDER_MIN_SOC
        assert january.target_soc < april.target_soc


class TestWinterFromTheForecast:
    WINTER_PLANS = SeasonRules(winter_uses_forecast=True)

    def test_a_winter_month_plans_from_the_forecast_instead_of_charging_to_100(self):
        decision = calculate_overnight_charge_target(_inputs(self.WINTER_PLANS), FORECAST, _on(1))

        assert "Winter month" not in decision.reason
        assert decision.target_soc < 100

    def test_the_floor_is_the_shoulder_minimum(self):
        decision = calculate_overnight_charge_target(_inputs(self.WINTER_PLANS), FORECAST, _on(1))

        assert decision.target_soc >= CHARGE_SHOULDER_MIN_SOC

    def test_a_summer_month_is_unchanged_by_the_setting(self):
        plain = calculate_overnight_charge_target(_inputs(), FORECAST, _on(6))
        planned = calculate_overnight_charge_target(_inputs(self.WINTER_PLANS), FORECAST, _on(6))

        assert planned == plain

    def test_a_higher_configured_minimum_still_wins_over_the_shoulder_floor(self):
        decision = calculate_overnight_charge_target(
            _inputs(self.WINTER_PLANS, min_soc=85), FORECAST, _on(1)
        )

        assert decision.target_soc >= 85

    def test_with_no_forecast_a_winter_month_still_plans_from_the_seasonal_estimate(self):
        decision = calculate_overnight_charge_target(
            _inputs(self.WINTER_PLANS), SolarForecast(forecast_kwh=None), _on(1)
        )

        assert decision.target_soc >= CHARGE_SHOULDER_MIN_SOC
