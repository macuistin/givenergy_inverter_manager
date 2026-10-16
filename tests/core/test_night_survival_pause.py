"""Night survival with a battery pause.

While the battery is paused the grid serves the house, so those hours add no consumption. The
figure changes by the load of the paused hours and by nothing else. The words name the pause once.
A night with no pause reads as it always did.
"""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.const import (
    SOLAR_NOISE_FLOOR_W,
    STATE_MAX_LENGTH,
)
from custom_components.givenergy_inverter_manager.core.battery import (
    NightEstimateInputs,
    PausedNight,
    SurvivalReport,
    estimate_will_survive_night,
    hours_until_solar,
    night_window,
    paused_night,
    survival_attributes,
)
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.text_state import fit_state

NIGHT = PauseWindow(time(23, 0), time(8, 0))
CAPACITY_KWH = 10.0
MIN_SOC = 20.0
HOURLY_KWH = 0.5
SOLAR_ON = SOLAR_NOISE_FLOOR_W


def _inputs(hour: int, soc: float, pause: PauseWindow | None, solar_w: float = 0.0):
    return NightEstimateInputs(
        current_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        min_soc=MIN_SOC,
        hours_until_solar=hours_until_solar(hour, solar_w),
        average_hourly_consumption_kwh=HOURLY_KWH,
        paused=paused_night(pause, hour, solar_w),
    )


def _points(kwh: float) -> float:
    return kwh / CAPACITY_KWH * 100


class TestTheNightWindow:
    @pytest.mark.parametrize(
        ("hour", "solar_w", "expected"),
        [
            (2, 0.0, (120, 6.0)),  # live night: from now to 08:00
            (20, 0.0, (1200, 12.0)),  # evening: from now to tomorrow's sunrise
            (11, 0.0, (660, 21.0)),  # daytime with no solar
            (11, SOLAR_ON, (0, 8.0)),  # solar on: tonight's 00:00 to 08:00
        ],
    )
    def test_where_it_starts_and_how_long_it_is(self, hour, solar_w, expected):
        assert night_window(hour, solar_w) == expected

    def test_hours_until_solar_is_its_length(self):
        assert hours_until_solar(20, 0.0) == 12.0


class TestWhichPausedHoursCount:
    @pytest.mark.parametrize(
        ("hour", "solar_w", "expected_hours"),
        [
            (20, 0.0, 9.0),  # 20:00 to 08:00 holds 23:00 to 08:00
            (23, 0.0, 9.0),
            (2, 0.0, 6.0),  # 02:00 to 08:00 is all paused
            (7, 0.0, 1.0),
            (11, SOLAR_ON, 8.0),  # 00:00 to 08:00 is all paused
        ],
    )
    def test_the_paused_hours_of_the_window(self, hour, solar_w, expected_hours):
        assert paused_night(NIGHT, hour, solar_w) == PausedNight(NIGHT, expected_hours)

    def test_no_pause_has_no_paused_night(self):
        assert paused_night(None, 20, 0.0) is None

    def test_a_pause_that_misses_the_night_is_not_part_of_it(self):
        daytime = PauseWindow(time(12, 0), time(14, 0))

        assert paused_night(daytime, 20, 0.0) is None


class TestTheEstimate:
    def test_without_a_pause_nothing_changes(self):
        survives, soc, reason = estimate_will_survive_night(_inputs(20, 90.0, None))

        # 12 hours at 0.5 kWh is 6 kWh, which is 60 points of the 10 kWh battery.
        assert survives is True
        assert soc == pytest.approx(90.0 - _points(6.0))
        assert reason == "Battery should last until solar. Estimated SoC at sunrise: 30%"

    def test_the_paused_hours_add_no_load(self):
        _, without, _ = estimate_will_survive_night(_inputs(20, 90.0, None))
        _, paused, _ = estimate_will_survive_night(_inputs(20, 90.0, NIGHT))

        # Nine of the twelve hours are paused: 4.5 kWh is not drawn from the battery.
        assert paused - without == pytest.approx(_points(9 * HOURLY_KWH))

    def test_a_pause_over_the_whole_window_leaves_the_battery_as_it_is(self):
        _, soc, _ = estimate_will_survive_night(_inputs(23, 62.0, NIGHT))

        assert soc == pytest.approx(62.0)

    def test_the_reason_says_when_the_battery_is_paused(self):
        _, _, reason = estimate_will_survive_night(_inputs(20, 90.0, NIGHT))

        assert reason == (
            "Battery should last until solar. Estimated SoC at sunrise: 75%. "
            "The battery is paused from 23:00 to 08:00."
        )

    def test_a_shortfall_that_the_pause_removes_is_no_shortfall(self):
        survives, _, reason = estimate_will_survive_night(_inputs(20, 40.0, None))
        paused_survives, _, paused_reason = estimate_will_survive_night(_inputs(20, 40.0, NIGHT))

        assert survives is False
        assert reason == "Battery may run low. Estimated shortfall: 4.0kWh before solar starts."
        assert paused_survives is True
        assert "run low" not in paused_reason

    def test_a_shortfall_that_is_left_names_the_pause_once(self):
        # 11:00 to 08:00 is 21 hours, 9 of them paused. 12 hours at 0.5 kWh is 6 kWh against the
        # 0.5 kWh the battery holds above its minimum.
        _, _, reason = estimate_will_survive_night(_inputs(11, 25.0, NIGHT))

        assert reason == (
            "Battery may run low. Estimated shortfall: 5.5kWh before solar starts. "
            "The battery is paused from 23:00 to 08:00."
        )

    def test_a_pause_outside_the_night_changes_nothing(self):
        daytime = PauseWindow(time(12, 0), time(14, 0))

        assert estimate_will_survive_night(_inputs(20, 90.0, daytime)) == (
            estimate_will_survive_night(_inputs(20, 90.0, None))
        )

    def test_a_partly_paused_night_changes_by_the_paused_hours_only(self):
        small_hours = PauseWindow(time(2, 0), time(6, 0))
        _, without, _ = estimate_will_survive_night(_inputs(23, 90.0, None))
        _, paused, _ = estimate_will_survive_night(_inputs(23, 90.0, small_hours))

        assert paused - without == pytest.approx(_points(4 * HOURLY_KWH))

    def test_the_reason_fits_a_sensor_state_whole(self):
        _, _, reason = estimate_will_survive_night(_inputs(20, 25.0, NIGHT))

        assert len(reason) <= STATE_MAX_LENGTH
        assert fit_state(reason).state == reason


def _report(pause: PauseWindow | None, **fields) -> SurvivalReport:
    base = {"will_survive": True, "estimated_soc": 62.0, "min_soc": 20.0, "current_soc": 62.0}
    base.update(fields)
    return SurvivalReport(
        base["will_survive"],
        base["estimated_soc"],
        base["min_soc"],
        base["current_soc"],
        base.get("reason", "Battery should last until solar. Estimated SoC at sunrise: 62%"),
        base.get("soc_with_charge"),
        pause,
    )


class TestTheWords:
    def test_without_a_pause_the_text_is_as_it_was(self):
        attrs = survival_attributes(_report(None))

        assert attrs["summary"] == "Lasts the night · 62% at sunrise"
        assert attrs["explanation"] == "Battery should last until solar. Estimated SoC at sunrise: 62%"

    def test_the_summary_names_the_pause_after_the_figure(self):
        attrs = survival_attributes(_report(NIGHT))

        assert attrs["summary"] == "Lasts the night · 62% at sunrise · battery paused 23:00 to 08:00"

    def test_the_explanation_names_the_pause_once(self):
        reason = (
            "Battery should last until solar. Estimated SoC at sunrise: 62%. "
            "The battery is paused from 23:00 to 08:00."
        )
        attrs = survival_attributes(_report(NIGHT, reason=reason))

        assert attrs["explanation"] == reason
        assert attrs["explanation"].count("paused") == 1

    def test_a_warning_explanation_says_it_once(self):
        attrs = survival_attributes(_report(NIGHT, estimated_soc=24.0))

        assert attrs["outlook"] == "Only just lasts the night"
        assert attrs["explanation"].endswith("The battery is paused from 23:00 to 08:00.")
        assert attrs["explanation"].count("paused") == 1

    def test_a_planned_charge_keeps_both_figures_and_names_the_pause_once(self):
        attrs = survival_attributes(_report(NIGHT, soc_with_charge=90.0))

        assert attrs["summary"] == (
            "Lasts the night · 62% at sunrise without a charge, about 90% with tonight's charge"
            " · battery paused 23:00 to 08:00"
        )
        assert attrs["explanation"].count("paused") == 1

    def test_a_critical_night_with_a_charge_says_it_once(self):
        reason = "Battery may run low. Estimated shortfall: 1.2kWh before solar starts."
        attrs = survival_attributes(
            _report(NIGHT, will_survive=False, estimated_soc=20.0, soc_with_charge=80.0, reason=reason)
        )

        assert attrs["explanation"].count("paused") == 1
        assert "Tonight's planned charge covers this" in attrs["explanation"]

    def test_the_pause_does_not_change_the_outlook_or_the_figures(self):
        with_pause = survival_attributes(_report(NIGHT))
        without = survival_attributes(_report(None))

        for key in ("outlook", "battery_soc", "estimated_soc_at_sunrise", "minimum_soc"):
            assert with_pause[key] == without[key]
