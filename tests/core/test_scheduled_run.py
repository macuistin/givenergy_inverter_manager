"""The longest a scheduled immersion run lasts: counting, the stop, and when it clears."""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.givenergy_inverter_manager.core.scheduled_run import (
    HeldScheduledRun,
    RunStep,
    advance,
    warning_state,
)

START = datetime(2031, 1, 15, 23, 0)
CYCLE = timedelta(seconds=30)


def _run(held, *, minutes, wanted=True, heater_on=True, limit=60, start=START):
    """Advance one cycle in 30 seconds for this many minutes."""
    for index in range(int(minutes * 2) + 1):
        advance(held, RunStep(start + CYCLE * index, wanted, heater_on, limit))
    return held


class TestCounting:
    def test_the_first_cycle_counts_nothing(self):
        held = HeldScheduledRun()
        advance(held, RunStep(START, True, True, 60))
        assert held.minutes == 0.0

    def test_minutes_count_while_the_heater_is_on_and_scheduled_heating_wants_it(self):
        held = _run(HeldScheduledRun(), minutes=20)
        assert held.minutes == 20.0
        assert not held.capped

    def test_minutes_do_not_count_while_the_heater_is_off(self):
        held = _run(HeldScheduledRun(), minutes=20, heater_on=False)
        assert held.minutes == 0.0

    def test_a_gap_longer_than_a_few_cycles_is_not_counted(self):
        held = HeldScheduledRun()
        advance(held, RunStep(START, True, True, 60))
        advance(held, RunStep(START + timedelta(minutes=30), True, True, 60))
        assert held.minutes == 0.0


class TestTheLimit:
    def test_the_run_is_capped_once_it_has_lasted_the_limit(self):
        held = _run(HeldScheduledRun(), minutes=60)
        assert held.capped

    def test_it_is_not_capped_a_cycle_early(self):
        held = _run(HeldScheduledRun(), minutes=59)
        assert not held.capped

    def test_a_capped_run_stays_capped_while_scheduled_heating_still_wants_the_heater(self):
        held = _run(HeldScheduledRun(), minutes=60)
        later = _run(held, minutes=120, heater_on=False, start=START + timedelta(hours=1, seconds=30))
        assert later.capped

    def test_a_shorter_limit_caps_sooner(self):
        assert _run(HeldScheduledRun(), minutes=30, limit=30).capped

    def test_a_limit_of_zero_means_no_limit(self):
        held = _run(HeldScheduledRun(), minutes=600, limit=0)
        assert not held.capped
        assert held.minutes == 0.0


class TestWhenItClears:
    def test_it_clears_when_scheduled_heating_stops_wanting_the_heater(self):
        held = _run(HeldScheduledRun(), minutes=60)
        advance(held, RunStep(START + timedelta(hours=2), False, False, 60))
        assert (held.minutes, held.capped) == (0.0, False)

    def test_a_new_run_then_counts_from_zero(self):
        held = _run(HeldScheduledRun(), minutes=60)
        advance(held, RunStep(START + timedelta(hours=2), False, False, 60))
        later = _run(held, minutes=10, start=START + timedelta(hours=3))
        assert later.minutes == 10.0
        assert not later.capped


class TestTheWarningState:
    def test_it_is_idle_until_the_limit_is_reached(self):
        held = _run(HeldScheduledRun(), minutes=20)
        assert warning_state(held, 60, enabled=True) == "idle"

    def test_it_says_reached_once_the_run_was_capped(self):
        held = _run(HeldScheduledRun(), minutes=60)
        assert warning_state(held, 60, enabled=True) == "reached"

    def test_it_is_off_when_the_warning_is_turned_off(self):
        held = _run(HeldScheduledRun(), minutes=60)
        assert warning_state(held, 60, enabled=False) == "off"

    def test_it_is_off_without_a_limit(self):
        assert warning_state(HeldScheduledRun(), 0, enabled=True) == "off"

    def test_it_goes_back_to_idle_when_the_run_ends(self):
        held = _run(HeldScheduledRun(), minutes=60)
        advance(held, RunStep(START + timedelta(hours=2), False, False, 60))
        assert warning_state(held, 60, enabled=True) == "idle"
