"""When a pause that stops charging covers the planned charge (core/charge_pause.py)."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.charge_pause import (
    BLOCKED_CYCLES,
    charge_is_blocked,
    next_step,
)
from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow


def _pause(start: str, end: str) -> PauseWindow:
    return PauseWindow(time.fromisoformat(start), time.fromisoformat(end))


def _window(start: str = "02:00", end: str = "04:30") -> ChargeWindow:
    return ChargeWindow(time.fromisoformat(start), time.fromisoformat(end), False, None, None)


class TestWhenThePauseOverlapsTheWindow:
    @pytest.mark.parametrize(
        ("pause", "window", "expected"),
        [
            (("23:00", "08:00"), ("02:00", "04:30"), True),  # wraps midnight, covers it
            (("01:00", "03:00"), ("02:00", "04:30"), True),  # covers the start
            (("03:00", "06:00"), ("02:00", "04:30"), True),  # covers the end
            (("02:30", "03:00"), ("02:00", "04:30"), True),  # inside the window
            (("09:00", "11:00"), ("02:00", "04:30"), False),  # a daytime pause
            (("04:30", "08:00"), ("02:00", "04:30"), False),  # starts as the window ends
            (("23:00", "02:00"), ("02:00", "04:30"), False),  # ends as the window starts
            (("08:00", "23:00"), ("23:30", "04:30"), False),  # window wraps midnight, pause is day
            (("02:00", "03:00"), ("23:30", "04:30"), True),  # window wraps midnight
            (("23:00", "08:00"), ("23:30", "04:30"), True),  # both wrap
        ],
    )
    def test_the_overlap(self, pause, window, expected):
        assert charge_is_blocked(_pause(*pause), _window(*window), skipped=False) is expected


class TestWhenNothingIsBlocked:
    def test_no_pause(self):
        assert charge_is_blocked(None, _window(), skipped=False) is False

    def test_no_window(self):
        assert charge_is_blocked(_pause("23:00", "08:00"), None, skipped=False) is False

    def test_a_skipped_night_plans_no_charge(self):
        assert charge_is_blocked(_pause("23:00", "08:00"), _window(), skipped=True) is False


class TestTheRepairWaitsForThreeCyclesInARow:
    def test_it_is_raised_on_the_third_cycle(self):
        count, raised = 0, []
        for _ in range(BLOCKED_CYCLES):
            step = next_step(blocked=True, blocked_cycles=count)
            count = step.blocked_cycles
            raised.append(step.raise_issue)

        assert raised == [False, False, True]

    def test_it_keeps_being_raised_while_blocked(self):
        assert next_step(blocked=True, blocked_cycles=BLOCKED_CYCLES).raise_issue is True

    def test_a_cycle_that_is_not_blocked_clears_it_and_starts_again(self):
        step = next_step(blocked=False, blocked_cycles=BLOCKED_CYCLES + 4)

        assert step.clear_issue is True
        assert step.raise_issue is False
        assert step.blocked_cycles == 0
