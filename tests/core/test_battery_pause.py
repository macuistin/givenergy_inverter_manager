"""PauseWindow: which part of a span, and which half hour slots, the battery is paused for.

The battery pause stops discharge in a time of day window. The window may wrap midnight, which
is the usual case (23:00 to 08:00), and its ends need not fall on a half hour.
"""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.core.battery_pause import (
    SLOTS_PER_DAY,
    PauseWindow,
    with_note,
)


def _window(start: str, end: str) -> PauseWindow:
    return PauseWindow(time.fromisoformat(start), time.fromisoformat(end))


def _paused_slots(window: PauseWindow) -> list[int]:
    return [slot for slot in range(SLOTS_PER_DAY) if window.is_slot_paused(slot)]


NIGHT = _window("23:00", "08:00")


class TestWhichSlotsArePaused:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            # A window inside one day.
            ("09:00", "11:00", [18, 19, 20, 21]),
            # A window that wraps midnight: the last two slots of the day, then 00:00 to 08:00.
            ("23:00", "08:00", [*range(0, 16), 46, 47]),
            # A window that ends on midnight does not wrap.
            ("22:00", "00:00", [44, 45, 46, 47]),
            # A window that starts on midnight.
            ("00:00", "02:00", [0, 1, 2, 3]),
            # A window that ends inside the cheap window of a night tariff (00:30 to 04:30).
            ("23:00", "02:00", [0, 1, 2, 3, 46, 47]),
            # Ends that fall inside a slot: a slot counts when more than half of it is paused (20 of 30
            # minutes, then 10 of 30).
            ("23:10", "07:50", [*range(0, 16), 46, 47]),
            ("23:20", "07:40", [*range(0, 15), 47]),
            # The whole day but one half hour.
            ("00:30", "00:00", list(range(1, 48))),
        ],
    )
    def test_the_slots_of_a_window(self, start, end, expected):
        assert _paused_slots(_window(start, end)) == expected

    def test_a_slot_half_covered_is_not_paused_but_has_the_fraction(self):
        window = _window("23:15", "08:00")

        assert window.paused_fraction(46) == pytest.approx(0.5)
        assert window.is_slot_paused(46) is False
        assert window.paused_fraction(47) == 1.0

    def test_a_window_with_the_same_start_and_end_pauses_nothing(self):
        window = _window("23:00", "23:00")

        assert _paused_slots(window) == []
        assert window.paused_minutes(0, 24 * 60) == 0.0

    def test_slots_outside_the_window_have_no_paused_share(self):
        assert [NIGHT.paused_fraction(slot) for slot in (16, 30, 45)] == [0.0, 0.0, 0.0]


class TestHowMuchOfASpanIsPaused:
    @pytest.mark.parametrize(
        ("from_hhmm", "hours", "expected_hours"),
        [
            ("22:00", 10.0, 9.0),  # evening to sunrise: 23:00 to 08:00 is paused
            ("00:00", 8.0, 8.0),  # the small hours, all paused
            ("08:00", 15.0, 0.0),  # sunrise to 23:00, none paused
            ("12:00", 24.0, 9.0),  # any whole day holds the whole window once
            ("23:30", 8.5, 8.5),  # starts inside the window
            ("07:00", 2.0, 1.0),  # ends after the window does
            ("20:00", 12.0, 9.0),  # a span that starts before and runs past midnight
            ("22:00", 48.0, 18.0),  # two days
        ],
    )
    def test_hours_paused(self, from_hhmm, hours, expected_hours):
        start = time.fromisoformat(from_hhmm)

        assert NIGHT.paused_hours(start.hour * 60 + start.minute, hours) == pytest.approx(
            expected_hours
        )

    def test_a_span_that_starts_on_a_later_day_counts_the_same(self):
        # 25:00 is 01:00 on the next day, which is inside the window.
        assert NIGHT.paused_minutes(25 * 60, 60) == 60.0

    def test_a_window_inside_one_day_is_not_paused_overnight(self):
        daytime = _window("09:00", "11:00")

        assert daytime.paused_hours(22 * 60, 10.0) == 0.0
        assert daytime.paused_hours(8 * 60, 4.0) == 2.0


class TestTheSpansTheBatteryServes:
    def test_a_span_with_no_pause_in_it_is_whole(self):
        assert NIGHT.unpaused_spans(9 * 60, 14 * 60) == [(540, 840)]

    def test_the_evening_before_the_pause_is_what_is_left(self):
        assert NIGHT.unpaused_spans(22 * 60, 10 * 60) == [(1320, 60)]

    def test_a_span_inside_the_pause_has_nothing_left(self):
        assert NIGHT.unpaused_spans(0, 8 * 60) == []

    def test_a_span_around_a_daytime_pause_is_in_two_parts(self):
        daytime = _window("12:00", "14:00")

        assert daytime.unpaused_spans(10 * 60, 6 * 60) == [(600, 120), (840, 120)]

    def test_the_parts_and_the_paused_minutes_add_up_to_the_span(self):
        spans = NIGHT.unpaused_spans(20 * 60, 12 * 60)

        assert sum(length for _, length in spans) + NIGHT.paused_minutes(20 * 60, 12 * 60) == 720


class TestTheWords:
    def test_the_window_as_text(self):
        assert NIGHT.text == "23:00 to 08:00"

    def test_the_note_is_a_sentence(self):
        assert NIGHT.note == "The battery is paused from 23:00 to 08:00."

    def test_a_text_without_a_pause_is_unchanged(self):
        assert with_note("Battery should last", None) == "Battery should last"

    def test_the_note_follows_the_text_as_a_new_sentence(self):
        assert with_note("Estimated SoC at sunrise: 63%", NIGHT) == (
            "Estimated SoC at sunrise: 63%. The battery is paused from 23:00 to 08:00."
        )

    def test_a_text_that_ends_in_a_full_stop_keeps_it(self):
        assert with_note("Shortfall 1.2kWh.", NIGHT) == (
            "Shortfall 1.2kWh. The battery is paused from 23:00 to 08:00."
        )

    def test_the_note_is_added_once(self):
        once = with_note("Battery lasts", NIGHT)

        assert with_note(once, NIGHT) == once
