"""Unit tests for core/overnight_phase.py: when the overnight plan is shown."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow
from custom_components.givenergy_inverter_manager.core.overnight_phase import (
    OvernightPhase,
    OvernightTimes,
    clock_text,
    overnight_phase,
    plan_ready_minute,
    window_end_minute,
)

SOLAR_END = 18 * 60  # solar expected to stop at 18:00
WINDOW_END = 5 * 60 + 40  # the charge window closes at 05:40
TIMES = OvernightTimes(SOLAR_END, WINDOW_END)


def _at(hour: int, minute: int = 0) -> float:
    return hour * 60 + minute


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 0, OvernightPhase.ACTIVE),  # just after midnight, the charge has not run yet
        (3, 30, OvernightPhase.ACTIVE),  # charging
        (5, 39, OvernightPhase.ACTIVE),  # the last minute of the window
        (5, 40, OvernightPhase.DONE),  # the window has closed
        (7, 59, OvernightPhase.DONE),  # still before the hour solar usually starts
        (8, 0, OvernightPhase.WAITING),  # daylight
        (12, 0, OvernightPhase.WAITING),
        (16, 59, OvernightPhase.WAITING),  # the minute before the plan shows
        (17, 0, OvernightPhase.ACTIVE),  # an hour before solar is expected to end
        (23, 0, OvernightPhase.ACTIVE),
    ],
)
def test_the_phase_follows_the_day(hour: int, minute: int, expected: OvernightPhase) -> None:
    assert overnight_phase(_at(hour, minute), TIMES) is expected


def test_solar_that_has_stopped_shows_the_plan_before_the_ready_time() -> None:
    stopped = OvernightTimes(SOLAR_END, WINDOW_END, solar_stopped=True)
    assert overnight_phase(_at(15, 0), stopped) is OvernightPhase.ACTIVE
    assert overnight_phase(_at(15, 0), TIMES) is OvernightPhase.WAITING


def test_solar_that_is_off_in_the_morning_does_not_show_the_plan() -> None:
    stopped = OvernightTimes(SOLAR_END, WINDOW_END, solar_stopped=True)
    assert overnight_phase(_at(9, 0), stopped) is OvernightPhase.WAITING


def test_a_window_that_runs_past_sunrise_leaves_no_done_time() -> None:
    times = OvernightTimes(SOLAR_END, 9 * 60)
    assert overnight_phase(_at(7, 59), times) is OvernightPhase.ACTIVE
    assert overnight_phase(_at(8, 0), times) is OvernightPhase.WAITING


def test_no_window_keeps_the_plan_until_solar_usually_starts() -> None:
    times = OvernightTimes(SOLAR_END, None)
    assert overnight_phase(_at(6, 0), times) is OvernightPhase.ACTIVE
    assert overnight_phase(_at(8, 0), times) is OvernightPhase.WAITING


def test_the_plan_shows_an_hour_before_solar_ends() -> None:
    assert plan_ready_minute(18 * 60) == 17 * 60
    assert plan_ready_minute(16 * 60 + 30) == 15 * 60 + 30


def test_the_ready_time_never_goes_before_midnight() -> None:
    assert plan_ready_minute(30) == 0


def test_a_late_solar_end_moves_the_ready_time_with_it() -> None:
    times = OvernightTimes(20 * 60, WINDOW_END)
    assert overnight_phase(_at(18, 30), times) is OvernightPhase.WAITING
    assert overnight_phase(_at(19, 0), times) is OvernightPhase.ACTIVE


def test_the_window_end_is_read_from_the_published_window() -> None:
    window = ChargeWindow(time(2, 0), time(5, 40), True, None, None)
    assert window_end_minute(window) == WINDOW_END
    assert window_end_minute(None) is None


@pytest.mark.parametrize(
    ("minute", "text"),
    [(0, "00:00"), (1020, "17:00"), (1025.4, "17:05"), (1439.6, "00:00")],
)
def test_the_clock_text_is_hours_and_minutes(minute: float, text: str) -> None:
    assert clock_text(minute) == text


class TestTheEngineSetsThePhase:
    """The engine reads the clock, the expected end of solar and the published window."""

    @staticmethod
    def _at(hour: int, minute: int = 0, **raw):
        from datetime import datetime

        from tests.conftest import _raw, _run

        data, _ = _run(raw=_raw(**raw), now=datetime(2026, 10, 16, hour, minute))
        return data

    def test_midday_waits_and_says_when_the_plan_will_be_ready(self) -> None:
        data = self._at(12, solar_power_w=3000.0)
        assert data.overnight_phase is OvernightPhase.WAITING
        assert data.overnight_plan_ready_at == "19:00"  # solar is expected to end at 20:00

    def test_the_evening_shows_the_plan(self) -> None:
        assert self._at(21, solar_power_w=0.0).overnight_phase is OvernightPhase.ACTIVE

    def test_after_the_window_closes_the_morning_is_done(self) -> None:
        data = self._at(6, solar_power_w=0.0)
        assert data.overnight_phase is OvernightPhase.DONE

    def test_daylight_after_that_waits(self) -> None:
        assert self._at(9, solar_power_w=800.0).overnight_phase is OvernightPhase.WAITING
