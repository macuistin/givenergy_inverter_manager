"""When tonight's charge target is worked out again inside the cheap window, and when it is written."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.charge_retry import WriteWindow
from custom_components.givenergy_inverter_manager.core.replan import (
    TRIGGER_EV,
    TRIGGER_FORECAST,
    TRIGGER_LATE,
    PlanBasis,
    ReplanInputs,
    count_replans,
    decide_replan,
    late_check_at,
    replan_note,
)

# The cheap window is 02:00 to 04:00, so the write fires at 01:59. The late check is at 03:00.
WINDOW = WriteWindow(
    datetime(2031, 3, 4, 1, 59, tzinfo=timezone.utc), datetime(2031, 3, 4, 4, 0, tzinfo=timezone.utc)
)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2031, 3, 4, hour, minute, tzinfo=timezone.utc)


def basis(forecast: float | None = 10.0, *, ev: bool = False, skipped: bool = False) -> PlanBasis:
    return PlanBasis(forecast, ev, skipped)


def inputs(**changes) -> ReplanInputs:
    base = ReplanInputs(
        now=at(2, 30),
        window=WINDOW,
        last_target=60,
        last_basis=basis(),
        new_target=70,
        new_basis=basis(),
        replans_so_far=0,
        override_active=False,
        late_check_done=False,
    )
    return replace(base, **changes)


class TestTheLateCheck:
    def test_it_is_the_later_of_half_an_hour_after_the_write_and_an_hour_before_the_end(self):
        assert late_check_at(WINDOW) == at(3, 0)
        long_window = WriteWindow(at(1, 0) - timedelta(days=1) + timedelta(hours=23), at(7, 30))
        assert late_check_at(long_window) == at(6, 30)
        short = WriteWindow(at(1, 59), at(2, 40))
        assert late_check_at(short) == at(2, 29)

    def test_nothing_is_checked_before_it_when_nothing_changed(self):
        assert not decide_replan(inputs(now=at(2, 59))).write

    def test_at_the_time_it_writes_a_target_that_moved_five_points(self):
        result = decide_replan(inputs(now=at(3, 0), new_target=65))
        assert (result.write, result.target, result.trigger) == (True, 65, TRIGGER_LATE)
        assert result.late_check_ran

    def test_it_runs_once_even_when_it_does_not_write(self):
        result = decide_replan(inputs(now=at(3, 0), new_target=62))
        assert not result.write
        assert result.late_check_ran

    def test_a_check_already_done_does_not_run_again(self):
        result = decide_replan(inputs(now=at(3, 10), late_check_done=True))
        assert not result.write
        assert not result.late_check_ran


class TestTheForecastTrigger:
    @pytest.mark.parametrize(
        ("last", "new", "fires"),
        [
            (10.0, 8.0, True),  # 20% and 2 kWh
            (10.0, 8.5, True),  # exactly 15% and 1.5 kWh
            (10.0, 8.6, False),  # 14% and 1.4 kWh: under the percentage
            (4.0, 3.0, True),  # 25% and exactly 1 kWh: both limits are inclusive
            (4.0, 2.9, True),  # 27% and 1.1 kWh
            (30.0, 28.5, False),  # 5% and 1.5 kWh: under the percentage
            (10.0, 11.5, True),  # a rise counts the same
        ],
    )
    def test_it_needs_fifteen_percent_and_one_kwh(self, last, new, fires):
        result = decide_replan(
            inputs(last_basis=basis(last), new_basis=basis(new), new_target=75)
        )
        assert result.write is fires
        if fires:
            assert result.trigger == TRIGGER_FORECAST

    def test_the_reason_says_which_way_and_how_far(self):
        fell = decide_replan(inputs(last_basis=basis(10.0), new_basis=basis(8.0), new_target=75))
        rose = decide_replan(inputs(last_basis=basis(10.0), new_basis=basis(12.0), new_target=50))
        assert fell.reason == "the forecast fell by 20%"
        assert rose.reason == "the forecast rose by 20%"

    def test_a_forecast_that_was_zero_is_judged_on_kwh_alone(self):
        result = decide_replan(inputs(last_basis=basis(0.0), new_basis=basis(2.0), new_target=40))
        assert result.write
        assert result.reason == "the forecast rose to 2.0 kWh"

    def test_the_day_after_forecast_triggers_too_with_its_own_wording(self):
        result = decide_replan(
            inputs(
                last_basis=PlanBasis(10.0, False, False, 12.0),
                new_basis=PlanBasis(10.0, False, False, 6.0),
                new_target=75,
            )
        )
        assert (result.write, result.trigger) == (True, TRIGGER_FORECAST)
        assert result.reason == "the forecast for the day after fell by 50%"

    def test_the_plans_own_figure_is_named_first_when_both_moved(self):
        result = decide_replan(
            inputs(
                last_basis=PlanBasis(10.0, False, False, 12.0),
                new_basis=PlanBasis(5.0, False, False, 6.0),
                new_target=75,
            )
        )
        assert result.reason == "the forecast fell by 50%"

    def test_a_missing_forecast_never_triggers(self):
        assert not decide_replan(inputs(last_basis=basis(None), new_basis=basis(5.0))).write
        assert not decide_replan(inputs(last_basis=basis(5.0), new_basis=basis(None))).write


class TestTheCarTrigger:
    def test_plugging_in_asks_for_a_check(self):
        result = decide_replan(inputs(new_basis=basis(ev=True), new_target=70))
        assert (result.write, result.trigger) == (True, TRIGGER_EV)
        assert result.reason == "the car was plugged in"

    def test_unplugging_asks_for_a_check(self):
        result = decide_replan(
            inputs(last_basis=basis(ev=True), new_basis=basis(ev=False), new_target=50)
        )
        assert (result.write, result.reason) == (True, "the car was unplugged")

    def test_a_car_that_stays_plugged_in_asks_for_nothing(self):
        both = inputs(last_basis=basis(ev=True), new_basis=basis(ev=True))
        assert not decide_replan(both).write


class TestTheRulesEveryWriteFollows:
    @pytest.mark.parametrize(
        ("new_target", "writes"),
        [(64, False), (65, True), (55, True), (56, False), (60, False)],
    )
    def test_a_write_needs_a_move_of_five_points(self, new_target, writes):
        result = decide_replan(inputs(now=at(3, 0), new_target=new_target))
        assert result.write is writes

    def test_a_target_below_the_charge_in_the_battery_is_allowed(self):
        assert decide_replan(inputs(now=at(3, 0), new_target=30)).write

    @pytest.mark.parametrize("used", [3, 4])
    def test_three_re_plans_a_night_is_the_most(self, used):
        assert not decide_replan(inputs(now=at(3, 0), replans_so_far=used)).write

    def test_two_re_plans_leave_one(self):
        assert decide_replan(inputs(now=at(3, 0), replans_so_far=2)).write

    @pytest.mark.parametrize(
        "now",
        [at(1, 59), at(0, 30), at(4, 0), at(5, 0)],
    )
    def test_nothing_is_written_outside_the_window(self, now):
        assert not decide_replan(inputs(now=now)).write

    def test_the_window_opens_a_minute_after_the_write(self):
        forecast_fell = {"last_basis": basis(10.0), "new_basis": basis(8.0), "new_target": 75}
        assert not decide_replan(inputs(now=at(1, 59), **forecast_fell)).write
        assert decide_replan(inputs(now=at(2, 0), **forecast_fell)).write

    @pytest.mark.parametrize(("now", "writes"), [(at(3, 44), True), (at(3, 45), True), (at(3, 46), False)])
    def test_fifteen_minutes_of_window_must_remain(self, now, writes):
        assert decide_replan(inputs(now=now, late_check_done=False)).write is writes

    def test_a_manual_override_stops_it_for_the_night(self):
        assert not decide_replan(inputs(now=at(3, 0), override_active=True)).write

    def test_a_skip_is_not_taken_while_a_charge_was_written(self):
        result = decide_replan(
            inputs(now=at(3, 0), new_basis=basis(skipped=True), new_target=20)
        )
        assert not result.write

    def test_a_skipped_night_can_become_a_charge(self):
        result = decide_replan(
            inputs(
                now=at(3, 0),
                last_basis=basis(skipped=True),
                last_target=20,
                new_basis=basis(),
                new_target=60,
            )
        )
        assert result.write

    def test_the_target_to_write_is_the_new_one(self):
        assert decide_replan(inputs(now=at(3, 0), new_target=77)).target == 77

    def test_a_held_decision_keeps_the_last_target(self):
        assert decide_replan(inputs(now=at(3, 0), new_target=61)).target == 60


class TestTheNoteAndTheCount:
    def test_the_note_names_the_time_and_the_cause(self):
        assert replan_note(at(3, 0), "the forecast fell by 20%") == (
            "Re-planned at 03:00: the forecast fell by 20%."
        )

    def test_it_counts_the_re_plan_notes_for_this_night_and_this_entity(self):
        entries = [
            {"time": at(0, 30).isoformat(), "entity_id": "number.t", "reason": "replan"},
            {"time": at(2, 10).isoformat(), "entity_id": "number.t", "reason": "replan"},
            {"time": at(2, 20).isoformat(), "entity_id": "number.t", "reason": "retry"},
            {"time": at(2, 40).isoformat(), "entity_id": "number.other", "reason": "replan"},
            {"time": at(3, 0).isoformat(), "entity_id": "number.t", "reason": "replan"},
            {"time": "not a time", "entity_id": "number.t", "reason": "replan"},
        ]
        assert count_replans(entries, "number.t", WINDOW.trigger) == 2
