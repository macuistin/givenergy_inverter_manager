"""When to retry the nightly charge write, and when a restart has to catch up."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.charge_retry import (
    Attempt,
    WriteWindow,
    latest_write_window,
    needs_catch_up,
    next_retry,
    retry_times,
)

TARGET = "number.target_soc"
# A night window 02:00 to 04:00 on 4 March. The trigger is 01:59.
DAY = datetime(2031, 3, 4, tzinfo=timezone.utc)
WINDOW = WriteWindow(DAY.replace(hour=1, minute=59), DAY.replace(hour=4))


def _at(hour: int, minute: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


def _entry(at: datetime, reason: str, entity: str = TARGET) -> dict:
    return {"time": at.isoformat(), "entity_id": entity, "value": "80", "reason": reason}


class TestLatestWriteWindow:
    def test_the_trigger_is_one_minute_before_the_start(self):
        window = latest_write_window(time(2, 0), time(4, 0), _at(1, 59))

        assert (window.trigger, window.end) == (_at(1, 59), _at(4))

    def test_before_tonights_trigger_it_is_last_nights_window(self):
        window = latest_write_window(time(2, 0), time(4, 0), _at(1, 0))

        assert window.trigger == _at(1, 59) - timedelta(days=1)
        assert window.end == _at(4) - timedelta(days=1)

    def test_a_window_that_crosses_midnight_ends_the_next_day(self):
        window = latest_write_window(time(23, 0), time(7, 0), _at(23, 30))

        assert window.trigger == _at(22, 59)
        assert window.end == _at(7) + timedelta(days=1)

    def test_a_start_at_midnight_triggers_the_evening_before(self):
        window = latest_write_window(time(0, 0), time(5, 0), _at(0, 10))

        assert window.trigger == DAY - timedelta(minutes=1)
        assert window.end == _at(5)

    def test_a_window_whose_end_equals_its_start_is_one_day(self):
        window = latest_write_window(time(2, 0), time(2, 0), _at(2, 5))

        assert window.end - window.trigger == timedelta(days=1, minutes=1)


class TestRetryTimes:
    def test_the_retries_are_two_five_ten_and_twenty_minutes_after_the_trigger(self):
        assert retry_times(WINDOW) == [_at(2, 1), _at(2, 4), _at(2, 9), _at(2, 19)]

    def test_a_retry_with_less_than_fifteen_minutes_of_window_left_is_dropped(self):
        short = WriteWindow(_at(1, 59), _at(2, 30))

        assert retry_times(short) == [_at(2, 1), _at(2, 4), _at(2, 9)]

    def test_exactly_fifteen_minutes_left_is_kept(self):
        edge = WriteWindow(_at(1, 59), _at(2, 34))  # 02:19 retry leaves exactly 15 minutes

        assert _at(2, 19) in retry_times(edge)

    def test_a_window_too_short_for_any_retry_has_none(self):
        assert retry_times(WriteWindow(_at(1, 59), _at(2, 10))) == []

    def test_the_next_retry_is_the_first_one_after_now(self):
        assert next_retry(WINDOW, _at(1, 59)) == _at(2, 1)
        assert next_retry(WINDOW, _at(2, 1)) == _at(2, 4)
        assert next_retry(WINDOW, _at(2, 19)) is None


class TestAttempt:
    def test_the_next_attempt_keeps_the_window_and_counts_up(self):
        attempt = Attempt(WINDOW).next()

        assert (attempt.window, attempt.number) == (WINDOW, 2)


class TestNeedsCatchUp:
    def test_inside_the_window_with_no_write_logged_it_does(self):
        assert needs_catch_up(WINDOW, _at(2, 30), [], TARGET)

    def test_before_the_trigger_it_does_not(self):
        assert not needs_catch_up(WINDOW, _at(1, 30), [], TARGET)

    def test_after_the_window_ends_it_does_not(self):
        assert not needs_catch_up(WINDOW, _at(4, 5), [], TARGET)

    def test_with_less_than_fifteen_minutes_left_it_does_not(self):
        assert not needs_catch_up(WINDOW, _at(3, 50), [], TARGET)

    def test_a_manager_write_since_the_trigger_means_it_is_done(self):
        assert not needs_catch_up(WINDOW, _at(2, 30), [_entry(_at(2, 0), "charge target")], TARGET)

    def test_a_write_before_the_trigger_is_last_nights(self):
        old = _entry(_at(2, 0) - timedelta(days=1), "charge target")

        assert needs_catch_up(WINDOW, _at(2, 30), [old], TARGET)

    def test_an_outside_change_is_not_the_managers_write(self):
        assert needs_catch_up(WINDOW, _at(2, 30), [_entry(_at(2, 0), "external")], TARGET)

    def test_a_write_to_another_entity_does_not_count(self):
        other = _entry(_at(2, 0), "charge window start", entity="select.start")

        assert needs_catch_up(WINDOW, _at(2, 30), [other], TARGET)

    def test_a_retry_note_after_the_last_write_means_the_write_failed(self):
        log = [_entry(_at(2, 0), "charge target"), _entry(_at(2, 1), "retry")]

        assert needs_catch_up(WINDOW, _at(2, 30), log, TARGET)

    def test_a_write_after_the_last_retry_note_means_it_worked(self):
        log = [_entry(_at(2, 1), "retry"), _entry(_at(2, 4), "charge target")]

        assert not needs_catch_up(WINDOW, _at(2, 30), log, TARGET)

    def test_a_retry_note_with_no_write_at_all_still_needs_it(self):
        assert needs_catch_up(WINDOW, _at(2, 30), [_entry(_at(2, 1), "retry")], TARGET)

    @pytest.mark.parametrize("stamp", ["not a time", "", None])
    def test_an_entry_with_an_unreadable_time_is_ignored(self, stamp):
        bad = {**_entry(_at(2, 0), "charge target"), "time": stamp}

        assert needs_catch_up(WINDOW, _at(2, 30), [bad], TARGET)
