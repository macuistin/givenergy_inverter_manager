"""Unit tests for the suggested oil schedule (core, no Home Assistant).

The oil costs 0.20 a kWh of heat and the immersion is 3 kW. The grid is 0.30 by day and 0.15 at
night, which is why heating in the cheap slot never makes a suggestion. The record is filled
the way the engine fills it: energy and cost added at a local time. Today is 15 December 2026.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.givenergy_inverter_manager.const import (
    OIL_SCHEDULE_MIN_DAYS,
    OIL_SCHEDULE_RECORD_DAYS,
)
from custom_components.givenergy_inverter_manager.core.oil_schedule import (
    HOURS_PER_DAY,
    ImmersionHeatLog,
    ScheduleQuery,
    suggest_oil_schedule,
)

TODAY = date(2026, 12, 15)
OIL = 0.20
DAY_RATE, NIGHT_RATE = 0.30, 0.15


def at(day: int, hour: int, minute: int = 30) -> datetime:
    return datetime(2026, 12, day, hour, minute)


def query(oil: float = OIL, heater_kw: float = 3.0) -> ScheduleQuery:
    return ScheduleQuery(today=TODAY, oil_cost_per_kwh=oil, heater_kw=heater_kw, currency_symbol="£")


def heat(log: ImmersionHeatLog, days: range, hour: int, kwh: float, rate: float = DAY_RATE):
    """Grid heat of *kwh* at *rate* in this hour on each of these days."""
    for day in days:
        log.add(at(day, hour), kwh, kwh * rate)


def observed(log: ImmersionHeatLog, days: range) -> None:
    """The days were watched and the immersion used no grid energy."""
    for day in days:
        log.add(at(day, 12), 0.0, 0.0)


def log_with(days: range, hour: int = 13, kwh: float = 1.5, rate: float = DAY_RATE):
    log = ImmersionHeatLog()
    heat(log, days, hour, kwh, rate)
    return log


TEN_DAYS = range(5, 15)  # 5 to 14 December, all complete before today


class TestWhenThereIsNothingToSay:
    def test_fewer_than_the_minimum_days_gives_nothing(self):
        few = range(15 - OIL_SCHEDULE_MIN_DAYS + 1, 15)  # one day short
        assert suggest_oil_schedule(log_with(few), query()) is None

    def test_the_minimum_number_of_days_is_enough(self):
        days = range(15 - OIL_SCHEDULE_MIN_DAYS, 15)
        result = suggest_oil_schedule(log_with(days), query())
        assert result is not None
        assert result.days == OIL_SCHEDULE_MIN_DAYS

    def test_today_is_not_counted_while_it_is_in_progress(self):
        log = log_with(range(9, 15))  # six complete days
        heat(log, range(15, 16), 13, 1.5)
        assert suggest_oil_schedule(log, query()) is None

    def test_an_empty_record_gives_nothing(self):
        assert suggest_oil_schedule(ImmersionHeatLog(), query()) is None

    def test_heating_in_the_cheap_slot_is_not_dearer_than_oil(self):
        result = suggest_oil_schedule(log_with(TEN_DAYS, hour=3, rate=NIGHT_RATE), query())
        assert result.days == 10
        assert result.windows == ()
        assert result.saving == 0.0
        assert result.sentence is None

    def test_oil_dearer_than_the_grid_gives_no_windows(self):
        result = suggest_oil_schedule(log_with(TEN_DAYS), query(oil=0.40))
        assert result.windows == ()
        assert result.sentence is None

    def test_oil_at_the_price_paid_saves_nothing(self):
        assert suggest_oil_schedule(log_with(TEN_DAYS), query(oil=DAY_RATE)).windows == ()

    def test_days_without_any_grid_heating_give_no_windows(self):
        log = ImmersionHeatLog()
        observed(log, TEN_DAYS)
        result = suggest_oil_schedule(log, query())
        assert result.days == 10
        assert result.windows == ()

    def test_a_trivial_saving_is_not_worth_a_schedule(self):
        """0.3 kWh a day at 0.01 over oil is a few pence a week."""
        result = suggest_oil_schedule(log_with(TEN_DAYS, kwh=0.3), query(oil=0.29))
        assert result.windows == ()

    def test_a_heater_of_no_power_gives_no_windows(self):
        assert suggest_oil_schedule(log_with(TEN_DAYS), query(heater_kw=0.0)).windows == ()


class TestWhatCountsAsARepeat:
    def test_an_hour_used_on_fewer_than_a_third_of_the_days_is_a_one_off(self):
        """Nine days need three: two guests' showers are not a habit."""
        log = ImmersionHeatLog()
        observed(log, range(6, 15))
        heat(log, range(6, 8), 13, 1.5)
        assert suggest_oil_schedule(log, query()).windows == ()

    def test_an_hour_used_on_a_third_of_the_days_is_a_habit(self):
        log = ImmersionHeatLog()
        observed(log, range(6, 15))
        heat(log, range(6, 9), 13, 1.5)
        assert suggest_oil_schedule(log, query()).windows == ("12:30 to 13:00",)

    def test_a_trickle_of_grid_energy_is_not_a_heating_run(self):
        """Solar surplus that does not quite cover the heater leaves a little on the grid."""
        assert suggest_oil_schedule(log_with(TEN_DAYS, kwh=0.1), query()).windows == ()

    def test_only_the_days_when_it_was_dearer_than_oil_count(self):
        """The same hour at a rate that varies by day: only the dear days are counted."""
        log = ImmersionHeatLog()
        observed(log, range(6, 15))
        heat(log, range(6, 12), 13, 1.5, rate=0.10)  # six cheap days
        heat(log, range(12, 15), 13, 1.5, rate=0.30)  # three dear days
        result = suggest_oil_schedule(log, query())
        assert result.saving == pytest.approx(3 * 1.5 * (0.30 - OIL))


class TestOneWindow:
    @pytest.fixture
    def result(self):
        return suggest_oil_schedule(log_with(TEN_DAYS), query())

    def test_the_oil_window_ends_where_the_immersion_started(self, result):
        """The immersion heated in the 13:00 hour. The oil runs just before that."""
        assert result.windows[-1].endswith("to 13:00")

    def test_the_run_is_as_long_as_the_heater_took(self, result):
        """1.5 kWh at 3 kW is half an hour."""
        assert result.windows == ("12:30 to 13:00",)

    def test_the_saving_is_what_oil_would_have_saved_over_the_record(self, result):
        assert result.saving == pytest.approx(10 * 1.5 * (DAY_RATE - OIL))

    def test_the_sentence_names_the_days_the_energy_the_hour_and_the_saving(self, result):
        assert result.sentence == (
            "Over the last 10 days the immersion used about 15 kWh of grid electricity that "
            "cost more than oil, mostly around 13:00. Running the oil from 12:30 to 13:00 "
            "would have saved about £1.50 over those days."
        )

    def test_a_longer_run_for_more_energy(self):
        """4.5 kWh at 3 kW is an hour and a half."""
        result = suggest_oil_schedule(log_with(TEN_DAYS, kwh=4.5), query())
        assert result.windows == ("11:30 to 13:00",)

    def test_a_smaller_heater_takes_longer_for_the_same_energy(self):
        result = suggest_oil_schedule(log_with(TEN_DAYS), query(heater_kw=1.5))
        assert result.windows == ("12:00 to 13:00",)

    def test_adjacent_hours_are_one_window_that_ends_at_the_first(self):
        log = log_with(TEN_DAYS, hour=13, kwh=3.0)
        heat(log, TEN_DAYS, 14, 3.0)
        result = suggest_oil_schedule(log, query())
        assert result.windows == ("11:00 to 13:00",)

    def test_a_run_before_midnight_is_shown_across_it(self):
        result = suggest_oil_schedule(log_with(TEN_DAYS, hour=0, kwh=3.0), query())
        assert result.windows == ("23:00 to 00:00",)

    def test_the_days_are_the_complete_days_in_the_record(self):
        log = log_with(range(8, 15))
        assert suggest_oil_schedule(log, query()).days == 7


class TestSeveralWindows:
    def test_two_separate_windows_are_listed_in_time_order(self):
        log = log_with(TEN_DAYS, hour=19, kwh=3.0)
        heat(log, TEN_DAYS, 13, 1.5)
        result = suggest_oil_schedule(log, query())
        assert result.windows == ("12:30 to 13:00", "18:00 to 19:00")
        assert result.saving == pytest.approx(10 * (1.5 + 3.0) * (DAY_RATE - OIL))

    def test_the_sentence_lists_both_hours_and_both_windows(self):
        log = log_with(TEN_DAYS, hour=19, kwh=3.0)
        heat(log, TEN_DAYS, 13, 1.5)
        sentence = suggest_oil_schedule(log, query()).sentence
        assert "mostly around 13:00 and 19:00" in sentence
        assert "Running the oil from 12:30 to 13:00 and 18:00 to 19:00" in sentence
        assert "about 45 kWh" in sentence

    def test_a_window_never_starts_before_the_heating_before_it_ended(self):
        """The 14:00 heating would want three hours, but 13:00 is where the earlier one ends."""
        log = log_with(TEN_DAYS, hour=12, kwh=3.0)
        heat(log, TEN_DAYS, 14, 9.0)
        result = suggest_oil_schedule(log, query())
        assert result.windows == ("11:00 to 12:00", "13:00 to 14:00")

    def test_at_most_three_windows_the_biggest_savings_first(self):
        log = ImmersionHeatLog()
        for hour, kwh in ((8, 1.0), (11, 4.0), (15, 3.0), (19, 2.0)):
            heat(log, TEN_DAYS, hour, kwh)
        result = suggest_oil_schedule(log, query())
        assert len(result.windows) == 3
        assert result.windows[0].endswith("to 11:00")
        assert not any(window.endswith("to 08:00") for window in result.windows)

    def test_a_window_below_the_trivial_saving_is_dropped_but_the_others_stay(self):
        log = log_with(TEN_DAYS, hour=19, kwh=3.0)
        heat(log, TEN_DAYS, 13, 0.3)
        assert suggest_oil_schedule(log, query()).windows == ("18:00 to 19:00",)


class TestTheRecord:
    def test_energy_and_cost_are_kept_for_the_local_hour(self):
        log = ImmersionHeatLog()
        log.add(at(15, 13, 5), 0.2, 0.06)
        log.add(at(15, 13, 40), 0.3, 0.09)
        (day,) = log.days
        assert day.date == "2026-12-15"
        assert day.kwh[13] == pytest.approx(0.5)
        assert day.cost[13] == pytest.approx(0.15)
        assert sum(day.kwh) == pytest.approx(0.5)

    def test_a_day_has_twenty_four_hours(self):
        log = ImmersionHeatLog()
        log.add(at(15, 0), 0.0, 0.0)
        assert len(log.days[0].kwh) == HOURS_PER_DAY == len(log.days[0].cost)

    def test_a_cycle_with_no_energy_still_records_the_day(self):
        log = ImmersionHeatLog()
        log.add(at(15, 9), 0.0, 0.0)
        assert [day.date for day in log.days] == ["2026-12-15"]

    def test_the_record_rolls_over_at_midnight(self):
        log = ImmersionHeatLog()
        log.add(datetime(2026, 12, 14, 23, 59), 0.1, 0.03)
        log.add(datetime(2026, 12, 15, 0, 1), 0.2, 0.06)
        first, second = log.days
        assert (first.date, second.date) == ("2026-12-14", "2026-12-15")
        assert first.kwh[23] == pytest.approx(0.1)
        assert first.kwh[0] == 0.0
        assert second.kwh[0] == pytest.approx(0.2)

    def test_a_late_reading_for_an_earlier_day_goes_to_that_day(self):
        log = ImmersionHeatLog()
        log.add(at(15, 9), 0.1, 0.03)
        log.add(at(14, 23), 0.2, 0.06)
        assert [day.date for day in log.days] == ["2026-12-14", "2026-12-15"]

    def test_only_the_last_fourteen_complete_days_and_today_are_kept(self):
        log = ImmersionHeatLog()
        for day in range(1, 29):
            log.add(datetime(2026, 12, day, 12), 0.1, 0.03)
        assert len(log.days) == OIL_SCHEDULE_RECORD_DAYS + 1
        assert log.days[0].date == "2026-12-14"
        assert log.days[-1].date == "2026-12-28"

    def test_the_record_holds_fourteen_days_of_twenty_four_hours(self):
        """Tiny: the stored form is a few hundred numbers."""
        log = ImmersionHeatLog()
        for day in range(1, 29):
            log.add(datetime(2026, 12, day, 12), 0.1, 0.03)
        numbers = sum(len(d["kwh"]) + len(d["cost"]) for d in log.to_storage())
        assert numbers == (OIL_SCHEDULE_RECORD_DAYS + 1) * HOURS_PER_DAY * 2

    def test_the_analysis_reads_at_most_fourteen_days(self):
        log = ImmersionHeatLog()
        for day in range(1, 28):
            log.add(datetime(2026, 12, day, 13), 1.5, 0.45)
        result = suggest_oil_schedule(log, ScheduleQuery(date(2026, 12, 28), OIL, 3.0, "£"))
        assert result.days == OIL_SCHEDULE_RECORD_DAYS


class TestStorage:
    def test_the_record_survives_a_round_trip(self):
        log = log_with(TEN_DAYS)
        restored = ImmersionHeatLog.from_storage(log.to_storage())
        before, after = suggest_oil_schedule(log, query()), suggest_oil_schedule(restored, query())
        assert (after.days, after.windows, after.sentence) == (
            before.days,
            before.windows,
            before.sentence,
        )

    def test_the_stored_form_is_plain_json(self):
        import json

        stored = log_with(range(10, 12)).to_storage()
        assert json.loads(json.dumps(stored)) == stored

    def test_nothing_stored_is_an_empty_record(self):
        assert ImmersionHeatLog.from_storage(None).days == []
        assert ImmersionHeatLog.from_storage([]).days == []

    @pytest.mark.parametrize(
        "damaged",
        [
            "text",
            {"date": "2026-12-14"},
            [None, 3, "x"],
            [{"date": "not a date", "kwh": [0.0] * 24, "cost": [0.0] * 24}],
            [{"date": "2026-12-14", "kwh": [0.0] * 5, "cost": [0.0] * 24}],
            [{"date": "2026-12-14", "kwh": ["a"] * 24, "cost": [0.0] * 24}],
            [{"date": "2026-12-14", "kwh": [0.0] * 24}],
        ],
    )
    def test_damaged_entries_are_skipped(self, damaged):
        assert ImmersionHeatLog.from_storage(damaged).days == []

    def test_a_good_entry_survives_a_damaged_one(self):
        good = log_with(range(10, 11)).to_storage()
        restored = ImmersionHeatLog.from_storage([None, *good])
        assert [day.date for day in restored.days] == ["2026-12-10"]

    def test_stored_days_are_in_date_order(self):
        newer, older = log_with(range(12, 13)).to_storage(), log_with(range(10, 11)).to_storage()
        restored = ImmersionHeatLog.from_storage([*newer, *older])
        assert [day.date for day in restored.days] == ["2026-12-10", "2026-12-12"]
