"""Unit tests for the ready-by planner and the learned heating rate (core, no Home Assistant)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_WINDOW_MARGIN,
    IMMERSION_RATE_RUN_MIN_MINUTES,
    IMMERSION_RATE_RUNS_KEPT,
)
from custom_components.givenergy_inverter_manager.core.immersion_rate import (
    SOURCE_ASSUMED,
    SOURCE_LEARNED,
    RunTracker,
    assumed_rate_c_per_h,
    keep_run,
    resolve_rate,
)
from custom_components.givenergy_inverter_manager.core.immersion_ready import (
    ReadyInputs,
    hours_to_heat,
    next_ready_at,
    parse_ready_times,
    place_hours,
    plan_ready,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

DUBLIN = ZoneInfo("Europe/Dublin")
TARGET = 55.0
RATE = 10.0  # degrees per hour
TARIFF = build_tariff(
    {
        "base_rate": 0.3334,
        "rate_periods": [
            {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
            {"name": "Nightboost", "rate": 0.0965, "start": "02:00", "end": "04:00"},
        ],
    }
)
MORNING, EVENING = time(7, 0), time(19, 0)


def at(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 12, day, hour, minute, tzinfo=DUBLIN)


def plan(now: datetime, temp: float | None, *times: time, rate: float = RATE):
    return plan_ready(ReadyInputs(TARIFF, now, times, temp, TARGET, rate))


class TestParsing:
    def test_times_are_sorted_and_deduplicated(self):
        assert parse_ready_times(["19:00", "07:00", "07:00"]) == (time(7), time(19))

    @pytest.mark.parametrize("raw", [None, "07:00", 7, [], ["soon", "25:00", "7"]])
    def test_nothing_usable_gives_no_times(self, raw):
        assert parse_ready_times(raw) == ()

    def test_seconds_are_ignored(self):
        assert parse_ready_times(["07:00:00"]) == (time(7),)

    def test_the_next_ready_time_rolls_to_tomorrow(self):
        assert next_ready_at(at(8), (MORNING, EVENING)) == at(19)
        assert next_ready_at(at(20), (MORNING, EVENING)) == at(7, day=16)
        assert next_ready_at(at(7), (MORNING,)) == at(7, day=16)
        assert next_ready_at(at(8), ()) is None


class TestHoursNeeded:
    def test_the_lead_time_carries_the_margin(self):
        assert hours_to_heat(45.0, TARGET, RATE) == pytest.approx(1.0 * (1 + CHARGE_WINDOW_MARGIN))

    def test_warm_water_needs_none(self):
        assert hours_to_heat(55.0, TARGET, RATE) == 0.0
        assert hours_to_heat(60.0, TARGET, RATE) == 0.0


class TestNothingToDo:
    def test_no_ready_times_means_no_plan(self):
        result = plan_ready(ReadyInputs(TARIFF, at(17), (), 30.0, TARGET, RATE))
        assert (result.ready_time, result.heat_now, result.expected_ready) == (None, False, None)

    def test_a_tank_at_the_target_is_ready(self):
        result = plan(at(17), 55.0, EVENING)
        assert (result.heat_now, result.expected_ready) == (False, True)
        assert result.ready_time == EVENING

    def test_an_unreadable_temperature_plans_nothing(self):
        result = plan(at(18), None, EVENING)
        assert (result.ready_time, result.heat_now, result.expected_ready) == (None, False, None)


class TestMorningReadyTime:
    """07:00 with the cheapest window 02:00 to 04:00 and the Night band to 08:00."""

    def test_nothing_runs_before_the_cheap_window(self):
        assert plan(at(1), 40.0, MORNING).heat_now is False

    def test_the_cheap_window_is_used_first(self):
        # 40 to 55 needs 1.725 h. The window gives 1 h from 03:00, the rest waits in the Night band.
        assert plan(at(3), 40.0, MORNING).heat_now is True

    def test_a_short_need_enters_the_window_late(self):
        # 49 to 55 needs 0.69 h. Heating sits at the end of the window, 03:18 to 04:00.
        assert plan(at(2), 49.0, MORNING).heat_now is False
        assert plan(at(3, 30), 49.0, MORNING).heat_now is True

    def test_the_night_band_is_used_after_the_window_not_the_base_rate(self):
        # 44 to 55 needs 1.265 h, so the Night band is entered at 05:44.
        assert plan(at(5, 30), 44.0, MORNING).heat_now is False
        assert plan(at(5, 44), 44.0, MORNING).heat_now is True
        assert plan(at(5, 44), 44.0, MORNING).expected_ready is True

    def test_a_late_cold_tank_is_flagged_as_not_ready_and_heats_at_once(self):
        result = plan(at(6), 40.0, MORNING)
        assert (result.heat_now, result.expected_ready) == (True, False)


class TestEveningReadyTime:
    """19:00 with only the base rate on offer from the morning until 23:00."""

    def test_a_cold_tank_at_17_00_heats_in_time(self):
        assert plan(at(17), 30.0, EVENING).heat_now is True

    def test_a_cool_tank_waits_so_that_solar_gets_the_day(self):
        assert plan(at(12), 45.0, EVENING).heat_now is False

    def test_a_top_up_at_17_00_finishes_by_19_00(self):
        """Run the plan minute by minute against a heater that warms 10 degrees an hour."""
        temp, now, ready_temp = 45.0, at(17), None
        while now < at(19):
            if plan(now, temp, EVENING).heat_now and temp < TARGET:
                temp += RATE / 60
            now += timedelta(minutes=1)
            ready_temp = temp
        assert ready_temp == pytest.approx(TARGET, abs=0.2)

    def test_the_run_cut_short_by_the_device_restarts_later(self):
        """The heater's own timer stopped it at 18:00 with the water below target."""
        # 52 to 55 needs 0.345 h, so the run restarts at 18:39 and finishes by 19:00.
        assert plan(at(18), 52.0, EVENING).heat_now is False
        assert plan(at(18, 45), 52.0, EVENING).heat_now is True


class TestARunInProgress:
    def test_a_running_heater_is_not_stopped_a_minute_before_its_band_is_used_up(self):
        """18:06 with 6.6 degrees to go: the plan would start at 18:07, but it already runs."""
        idle = ReadyInputs(TARIFF, at(18, 6), (EVENING,), 48.4, TARGET, 8.6)
        running = ReadyInputs(TARIFF, at(18, 6), (EVENING,), 48.4, TARGET, 8.6, heater_on=True)
        assert plan_ready(idle).heat_now is False
        assert plan_ready(running).heat_now is True

    def test_a_running_heater_stops_when_the_current_band_is_not_in_the_plan(self):
        """At 12:00 the plan would not start for hours, so a heater turned on for another reason goes."""
        running = ReadyInputs(TARIFF, at(12), (EVENING,), 50.0, TARGET, RATE, heater_on=True)
        assert plan_ready(running).heat_now is False


class TestAfterTheReadyTime:
    def test_the_next_ready_time_is_the_evening_after_the_morning(self):
        assert plan(at(7, 1), 50.0, MORNING, EVENING).ready_time == EVENING

    def test_the_morning_is_next_after_the_evening(self):
        assert plan(at(19, 1), 50.0, MORNING, EVENING).ready_time == MORNING

    def test_the_hours_needed_are_reported(self):
        assert plan(at(12), 45.0, EVENING).hours_needed == pytest.approx(1.15)


class TestAssumedRate:
    def test_a_three_kilowatt_element_in_a_large_cylinder(self):
        assert assumed_rate_c_per_h(3000.0) == pytest.approx(8.6, abs=0.1)

    def test_no_element_power_gives_no_rate(self):
        assert assumed_rate_c_per_h(0.0) == 0.0

    def test_nothing_learned_uses_the_assumed_rate(self):
        assert resolve_rate([], 3000.0) == (pytest.approx(8.6, abs=0.1), SOURCE_ASSUMED)

    def test_the_median_of_the_learned_runs_is_used(self):
        assert resolve_rate([6.0, 12.0, 9.0], 3000.0) == (9.0, SOURCE_LEARNED)

    def test_only_the_latest_runs_are_kept(self):
        rates: list[float] = []
        for value in range(IMMERSION_RATE_RUNS_KEPT + 3):
            rates = keep_run(rates, float(value))
        assert rates == [float(v) for v in range(3, IMMERSION_RATE_RUNS_KEPT + 3)]


class TestLearningFromRuns:
    def _run(self, tracker, minutes: int, start: float, rate: float) -> float | None:
        now = at(2)
        for step in range(0, minutes + 1, 5):
            tracker.observe(now + timedelta(minutes=step), start + rate * step / 60)
        return tracker.observe(now + timedelta(minutes=minutes + 1), None)

    def test_a_finished_run_reports_its_rate(self):
        assert self._run(RunTracker(), 60, 40.0, 9.0) == pytest.approx(9.0, rel=0.02)

    def test_a_short_run_is_not_a_sample(self):
        assert self._run(RunTracker(), IMMERSION_RATE_RUN_MIN_MINUTES - 10, 40.0, 9.0) is None

    def test_a_run_that_hardly_warmed_the_water_is_not_a_sample(self):
        assert self._run(RunTracker(), 30, 54.0, 1.0) is None

    def test_a_lost_reading_ends_the_run(self):
        tracker = RunTracker()
        for step in range(0, 65, 5):
            tracker.observe(at(2) + timedelta(minutes=step), 40.0 + step * 0.15)
        assert tracker.observe(at(3, 10), None) == pytest.approx(9.0, rel=0.02)

    def test_a_gap_in_the_cycles_splits_the_run(self):
        tracker = RunTracker()
        for step in range(0, 65, 5):
            tracker.observe(at(2) + timedelta(minutes=step), 40.0 + step * 0.15)
        # Home Assistant was down for an hour. The first run ends, a new one starts.
        assert tracker.observe(at(4, 10), 45.0) == pytest.approx(9.0, rel=0.02)

    def test_no_run_means_no_sample(self):
        assert RunTracker().observe(at(2), None) is None


class TestWherePlanPlacesItsHours:
    """place_hours is what plan_ready reads: the fallback start and the grid rate of the plan."""

    def test_one_band_puts_the_hours_at_its_end(self):
        placed = place_hours(TARIFF, at(15), at(19), 1.0)
        assert placed.fits is True
        assert placed.starts_at == at(18)
        assert placed.average_rate == pytest.approx(0.3334)

    def test_hours_that_do_not_fit_start_now(self):
        placed = place_hours(TARIFF, at(15), at(19), 5.0)
        assert placed.fits is False
        assert placed.starts_at == at(15)

    def test_the_cheapest_bands_fill_first_and_the_start_is_the_earliest_used(self):
        placed = place_hours(TARIFF, at(21), at(7, day=16), 3.0)
        assert placed.starts_at == at(2, day=16)
        assert placed.average_rate == pytest.approx((2 * 0.0965 + 1 * 0.1644) / 3)

    def test_a_partly_used_band_is_entered_late(self):
        placed = place_hours(TARIFF, at(1), at(7), 1.0)
        assert placed.starts_at == at(3)

    def test_a_full_band_starts_where_the_band_starts(self):
        assert place_hours(TARIFF, at(1), at(7), 2.0).starts_at == at(2)

    def test_the_start_is_a_real_hour_back_across_a_clock_change(self):
        """On 25 October 2026 the clocks go back at 02:00, so 00:00 to 04:00 is five real hours."""
        now, ready = datetime(2026, 10, 25, 0, 0, tzinfo=DUBLIN), datetime(2026, 10, 25, 4, 0, tzinfo=DUBLIN)
        start = place_hours(build_tariff({"base_rate": 0.30, "rate_periods": []}), now, ready, 1.0).starts_at
        assert start.astimezone(ZoneInfo("UTC")) == ready.astimezone(ZoneInfo("UTC")) - timedelta(hours=1)
