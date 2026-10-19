"""The heating rate is the average of the daily rates of the last 7 days.

A day's rate is the average of that day's runs. With one day of data that day is used as it is.
An install from before the daily rates has the median of its last runs until a dated run is
recorded. Runs of top-up size now count, because the days they fall on are averaged.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationStore,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import (
    IMMERSION_RATE_DAYS_KEPT,
    IMMERSION_RATE_RUN_MIN_MINUTES,
    IMMERSION_RATE_RUN_MIN_RISE_C,
)
from custom_components.givenergy_inverter_manager.lib.heating.rate import (
    SOURCE_ASSUMED,
    SOURCE_LEARNED,
    RunTracker,
    day_rates,
    keep_day_rate,
    resolve_rate,
)

DAY = date(2031, 3, 10)


def _days(*rates_by_day: tuple[int, list[float]]) -> list[dict]:
    days: list[dict] = []
    for offset, rates in rates_by_day:
        for rate in rates:
            days = keep_day_rate(days, DAY + timedelta(days=offset), rate)
    return days


class TestKeepingTheDays:
    def test_a_run_starts_a_day(self):
        days = keep_day_rate([], DAY, 9.0)
        assert days == [{"date": "2031-03-10", "total": 9.0, "runs": 1}]

    def test_two_runs_on_one_day_are_one_day_with_both(self):
        days = _days((0, [8.0, 10.0]))
        assert len(days) == 1
        assert day_rates(days) == [9.0]

    def test_days_are_kept_oldest_first_whatever_order_they_arrive_in(self):
        days = _days((2, [9.0]), (0, [9.0]), (1, [9.0]))
        assert [d["date"] for d in days] == ["2031-03-10", "2031-03-11", "2031-03-12"]

    def test_only_the_last_seven_days_are_kept(self):
        days = _days(*[(offset, [float(offset + 1)]) for offset in range(IMMERSION_RATE_DAYS_KEPT + 3)])
        assert len(days) == IMMERSION_RATE_DAYS_KEPT
        assert days[0]["date"] == (DAY + timedelta(days=3)).isoformat()

    def test_the_stored_list_is_not_changed_in_place(self):
        days = _days((0, [9.0]))
        keep_day_rate(days, DAY, 12.0)
        assert days == [{"date": "2031-03-10", "total": 9.0, "runs": 1}]


class TestTheRateToPlanWith:
    def test_one_day_of_data_is_used_as_it_is(self):
        assert resolve_rate([], 3000.0, _days((0, [11.0]))) == (11.0, SOURCE_LEARNED)

    def test_several_days_are_averaged(self):
        days = _days((0, [8.0]), (1, [10.0]), (2, [12.0]))
        assert resolve_rate([], 3000.0, days) == (pytest.approx(10.0), SOURCE_LEARNED)

    def test_a_day_with_several_runs_counts_once(self):
        # Day one has three runs at 6, day two has one at 12. The days are 6 and 12, so 9.
        days = _days((0, [6.0, 6.0, 6.0]), (1, [12.0]))
        assert resolve_rate([], 3000.0, days)[0] == pytest.approx(9.0)

    def test_the_week_follows_the_heater_as_old_days_drop_out(self):
        days = _days(*[(offset, [8.0]) for offset in range(7)], (7, [14.0]))
        rate = resolve_rate([], 3000.0, days)[0]
        assert rate == pytest.approx((6 * 8.0 + 14.0) / 7)

    def test_daily_rates_win_over_the_older_run_rates(self):
        assert resolve_rate([5.0, 5.0, 5.0], 3000.0, _days((0, [11.0])))[0] == 11.0

    def test_an_install_from_before_has_the_median_of_its_runs(self):
        assert resolve_rate([6.0, 12.0, 9.0], 3000.0, []) == (9.0, SOURCE_LEARNED)

    def test_nothing_learned_is_the_assumed_rate(self):
        rate, source = resolve_rate([], 3000.0, [])
        assert source == SOURCE_ASSUMED
        assert rate == pytest.approx(8.6, abs=0.1)

    def test_a_damaged_day_is_ignored(self):
        days = [{"date": "x", "total": 0.0, "runs": 0}, *_days((0, [10.0]))]
        assert day_rates(days) == [10.0]


class TestTopUpRunsCount:
    def _run(self, minutes: int, rise: float) -> float | None:
        tracker = RunTracker()
        start = datetime(2031, 3, 10, 2, 0, tzinfo=timezone.utc)
        for step in range(0, minutes + 1):
            tracker.observe(start + timedelta(minutes=step), 50.0 + rise * step / minutes)
        return tracker.observe(start + timedelta(minutes=minutes + 1), None)

    def test_a_ten_minute_run_that_warmed_the_water_a_degree_is_a_sample(self):
        assert IMMERSION_RATE_RUN_MIN_MINUTES <= 10
        assert IMMERSION_RATE_RUN_MIN_RISE_C <= 1.0
        assert self._run(10, 1.5) == pytest.approx(9.0, rel=0.05)

    def test_a_run_under_the_minimum_is_still_not_one(self):
        assert self._run(IMMERSION_RATE_RUN_MIN_MINUTES - 3, 3.0) is None


class TestStorage:
    def test_the_days_survive_a_save_and_load(self):
        days = _days((0, [8.0, 10.0]), (1, [12.0]))
        state = _deserialize({"immersion_rate_days": days})
        assert _serialize(state)["immersion_rate_days"] == days

    def test_a_payload_from_before_has_no_days(self):
        state = _deserialize({"immersion_heating_rates": [6.0, 9.0]})
        assert state.immersion_rate_days == []
        assert state.immersion_heating_rates == [6.0, 9.0]

    @pytest.mark.parametrize(
        "damaged",
        [None, "text", [{"date": "2031-03-10"}], [{"date": "2031-03-10", "total": 9.0, "runs": 0}], [5]],
    )
    def test_damaged_days_load_as_none(self, damaged):
        assert _deserialize({"immersion_rate_days": damaged}).immersion_rate_days == []

    def test_recording_a_run_keeps_it_under_its_day(self):
        store = AccumulationStore.__new__(AccumulationStore)
        store.state = _deserialize({})
        store.schedule_save = lambda: None
        store.record_immersion_rate(9.0, DAY)
        store.record_immersion_rate(11.0, DAY)
        assert store.immersion_rate_days == [{"date": "2031-03-10", "total": 20.0, "runs": 2}]
