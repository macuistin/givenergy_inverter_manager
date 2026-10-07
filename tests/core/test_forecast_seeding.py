"""Forecast accuracy records rebuilt from recorded forecast and solar readings."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.forecast_seeding import (
    Reading,
    RecordedReadings,
    local_midnight,
    query_start,
    seed_forecast_records,
)
from custom_components.givenergy_inverter_manager.core.rules import forecast_accuracy

DUBLIN = ZoneInfo("Europe/Dublin")
TODAY = date(2026, 6, 15)  # a Monday, local clock one hour ahead of UTC (summer time)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DUBLIN)


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def a_day(
    days_ago: int, forecast: float, actual: float
) -> tuple[list[Reading], list[Reading]]:
    """The readings of one day: the forecast seen at 23:50 the evening before, the solar total."""
    day = ago(days_ago)
    forecasts = [Reading(at(day - timedelta(days=1), 23, 50), forecast)]
    solar = [Reading(at(day, 12), actual / 2), Reading(at(day, 21), actual)]
    return forecasts, solar


def readings_of(*days: tuple[list[Reading], list[Reading]]) -> RecordedReadings:
    return RecordedReadings(
        forecasts=[r for f, _ in days for r in f],
        solar_totals=[r for _, s in days for r in s],
    )


def seed(readings: RecordedReadings, days: int = 14) -> list[dict]:
    return seed_forecast_records(readings, TODAY, DUBLIN, days)


class TestPairing:
    def test_pairs_the_forecast_before_midnight_with_that_days_solar(self):
        records = seed(readings_of(a_day(1, forecast=20.0, actual=14.0)))

        assert records == [{"forecast": 20.0, "actual": 14.0, "clipped": False}]

    def test_records_run_oldest_first(self):
        records = seed(
            readings_of(
                a_day(3, forecast=10.0, actual=7.0),
                a_day(2, forecast=20.0, actual=12.0),
                a_day(1, forecast=30.0, actual=15.0),
            )
        )

        assert [r["forecast"] for r in records] == [10.0, 20.0, 30.0]

    def test_the_last_forecast_before_midnight_wins(self):
        day = ago(1)
        eve = day - timedelta(days=1)
        readings = RecordedReadings(
            forecasts=[
                Reading(at(eve, 6), 25.0),
                Reading(at(eve, 18), 22.0),
                Reading(at(eve, 23, 59), 18.0),
                Reading(at(day, 0, 1), 9.0),  # after midnight, belongs to the next day
            ],
            solar_totals=[Reading(at(day, 20), 13.0)],
        )

        assert seed(readings)[0]["forecast"] == 18.0

    def test_readings_need_no_particular_order(self):
        forecasts, solar = a_day(1, forecast=20.0, actual=14.0)
        readings = RecordedReadings(forecasts=[*forecasts[::-1]], solar_totals=solar[::-1])

        assert seed(readings)[0] == {"forecast": 20.0, "actual": 14.0, "clipped": False}

    def test_a_forecast_unchanged_for_days_still_serves_each_midnight(self):
        readings = RecordedReadings(
            forecasts=[Reading(at(ago(5), 22), 16.0)],
            solar_totals=[Reading(at(ago(2), 20), 8.0), Reading(at(ago(1), 20), 9.0)],
        )

        assert [r["forecast"] for r in seed(readings)] == [16.0, 16.0]


class TestActualSolar:
    def test_the_day_total_is_the_highest_counter_value_of_the_local_day(self):
        day = ago(1)
        readings = RecordedReadings(
            forecasts=[Reading(at(day - timedelta(days=1), 23), 20.0)],
            solar_totals=[
                Reading(at(day - timedelta(days=1), 23, 59), 99.0),  # previous day
                Reading(at(day, 0, 0), 0.0),
                Reading(at(day, 12), 6.2),
                Reading(at(day, 23, 58), 13.4),
                Reading(at(day + timedelta(days=1), 0, 1), 0.0),  # reset, next day
            ],
        )

        assert seed(readings)[0]["actual"] == 13.4

    def test_a_dark_day_keeps_a_zero_total(self):
        records = seed(readings_of(a_day(1, forecast=12.0, actual=0.0)))

        assert records == [{"forecast": 12.0, "actual": 0.0, "clipped": False}]

    def test_the_day_boundary_is_local_midnight_not_utc(self):
        """23:30 UTC is already the next local day in summer, so it is not yesterday's total."""
        day = ago(1)
        late_utc = datetime(day.year, day.month, day.day, 23, 30, tzinfo=timezone.utc)
        readings = RecordedReadings(
            forecasts=[Reading(at(day - timedelta(days=1), 23), 20.0)],
            solar_totals=[Reading(at(day, 20), 11.0), Reading(late_utc, 80.0)],
        )

        assert seed(readings)[0]["actual"] == 11.0


class TestGaps:
    def test_a_day_without_a_recorded_forecast_is_left_out(self):
        _, solar = a_day(1, forecast=20.0, actual=14.0)

        assert seed(RecordedReadings(forecasts=[], solar_totals=solar)) == []

    def test_a_day_without_a_solar_total_is_left_out(self):
        forecasts, _ = a_day(1, forecast=20.0, actual=14.0)

        assert seed(RecordedReadings(forecasts=forecasts, solar_totals=[])) == []

    def test_a_forecast_recorded_after_the_day_ended_does_not_count(self):
        day = ago(1)
        readings = RecordedReadings(
            forecasts=[Reading(at(day, 8), 20.0)],
            solar_totals=[Reading(at(day, 20), 14.0)],
        )

        assert seed(readings) == []

    def test_a_zero_forecast_is_skipped_like_the_live_tracking_skips_it(self):
        day = ago(1)
        eve = day - timedelta(days=1)
        readings = RecordedReadings(
            forecasts=[Reading(at(eve, 20), 17.0), Reading(at(eve, 23, 59), 0.0)],
            solar_totals=[Reading(at(day, 20), 14.0)],
        )

        assert seed(readings)[0]["forecast"] == 17.0

    def test_today_is_never_included(self):
        forecasts, solar = a_day(0, forecast=20.0, actual=9.0)

        assert seed(RecordedReadings(forecasts=forecasts, solar_totals=solar)) == []

    def test_only_the_requested_number_of_days_is_read(self):
        readings = readings_of(*[a_day(n, 10.0, 8.0) for n in range(1, 21)])

        assert len(seed(readings, days=14)) == 14
        assert len(seed(readings, days=3)) == 3

    def test_no_readings_gives_no_records(self):
        assert seed(RecordedReadings(forecasts=[], solar_totals=[])) == []


class TestQueryWindow:
    def test_starts_an_hour_before_the_midnight_the_oldest_forecast_must_precede(self):
        start = query_start(TODAY, 14, DUBLIN)

        assert start == local_midnight(ago(14), DUBLIN) - timedelta(hours=1)
        assert start.tzinfo is not None

    def test_a_forecast_held_since_before_the_window_still_pairs_with_the_first_day(self):
        """The recorder reports the state in force at the query start, stamped with that time."""
        start = query_start(TODAY, 14, DUBLIN)
        readings = RecordedReadings(
            forecasts=[Reading(start, 18.0)],
            solar_totals=[Reading(at(ago(14), 20), 10.0)],
        )

        assert seed(readings, days=14) == [{"forecast": 18.0, "actual": 10.0, "clipped": False}]


class TestDaylightSavingDays:
    def test_the_spring_forward_day_is_local_midnight_to_local_midnight(self):
        today = date(2026, 3, 30)  # clocks went forward on Sunday 29 March
        day = date(2026, 3, 29)
        readings = RecordedReadings(
            forecasts=[Reading(datetime(2026, 3, 28, 23, 50, tzinfo=DUBLIN), 12.0)],
            solar_totals=[
                Reading(datetime(2026, 3, 29, 18, 0, tzinfo=DUBLIN), 7.5),
                Reading(datetime(2026, 3, 30, 0, 5, tzinfo=DUBLIN), 0.0),
            ],
        )

        assert seed_forecast_records(readings, today, DUBLIN, 1) == [
            {"forecast": 12.0, "actual": 7.5, "clipped": False}
        ]
        assert local_midnight(day, DUBLIN).utcoffset() == timedelta(0)
        assert local_midnight(today, DUBLIN).utcoffset() == timedelta(hours=1)


class TestWhatTheCorrectionMakesOfThem:
    def test_nine_recorded_days_are_enough_to_apply_the_correction_at_once(self):
        """The recorder keeps about ten days, so a new install has nine pairs to start from."""
        readings = readings_of(*[a_day(n, forecast=20.0, actual=14.0) for n in range(1, 10)])

        accuracy = forecast_accuracy(seed(readings))

        assert accuracy.applied
        assert accuracy.usable_days == 9
        assert accuracy.applied_factor == pytest.approx(0.7)
        assert accuracy.status == "Applied: x0.70 from 9 usable days"

    def test_four_recorded_days_are_still_waiting(self):
        readings = readings_of(*[a_day(n, forecast=20.0, actual=14.0) for n in range(1, 5)])

        assert forecast_accuracy(seed(readings)).status == "Waiting for data: 4 of 5 days"
