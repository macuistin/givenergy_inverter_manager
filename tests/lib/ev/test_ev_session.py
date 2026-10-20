"""The EV charging session: when it starts and ends, what it adds up, and the recent charges table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import EV_RECENT_SESSIONS_MAX
from custom_components.givenergy_inverter_manager.lib.ev import EVChargerState
from custom_components.givenergy_inverter_manager.lib.ev.session import (
    NO_FINISHED_SESSIONS,
    EVSession,
    EVSessionLog,
    EVSessionStep,
    recent_table,
    track_session,
)

PLUGGED = EVChargerState.CONNECTED
CHARGING = EVChargerState.CHARGING
UNPLUGGED = EVChargerState.DISCONNECTED
UNKNOWN = EVChargerState.UNKNOWN
EVENING = datetime(2031, 10, 15, 23, 10, tzinfo=timezone.utc)


def _step(now, state, energy_kwh=0.0, cost=0.0) -> EVSessionStep:
    return EVSessionStep(now=now, charger_state=state, energy_kwh=energy_kwh, cost=cost)


def _charge(log, start, *, kwh=1.0, cost=0.2, minutes=60):
    """Plug in at start, deliver kwh at cost, unplug minutes later."""
    track_session(log, _step(start, PLUGGED))
    track_session(log, _step(start + timedelta(minutes=minutes), CHARGING, kwh, cost))
    track_session(log, _step(start + timedelta(minutes=minutes + 1), UNPLUGGED))


class TestSessionBoundaries:
    def test_plugging_in_starts_a_session_at_that_cycle(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        assert log.current == EVSession(start=EVENING)
        assert log.plugged_in is True

    def test_an_unplugged_charger_starts_nothing(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, UNPLUGGED, 0.5, 0.1))
        assert log.current is None
        assert log.latest is None

    def test_each_step_adds_its_energy_and_cost(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        track_session(log, _step(EVENING + timedelta(seconds=30), CHARGING, 0.06, 0.006))
        track_session(log, _step(EVENING + timedelta(seconds=60), CHARGING, 0.06, 0.006))
        assert log.current.energy_kwh == pytest.approx(0.12)
        assert log.current.cost == pytest.approx(0.012)

    def test_a_session_keeps_counting_across_midnight(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        track_session(log, _step(EVENING + timedelta(minutes=40), CHARGING, 4.0, 0.4))
        after_midnight = EVENING + timedelta(hours=2)
        track_session(log, _step(after_midnight, CHARGING, 6.0, 0.6))
        track_session(log, _step(after_midnight + timedelta(hours=5), UNPLUGGED))
        finished = log.recent[0]
        assert finished.start == EVENING
        assert finished.end == after_midnight + timedelta(hours=5)
        assert finished.energy_kwh == pytest.approx(10.0)
        assert finished.cost == pytest.approx(1.0)

    def test_unplugging_ends_the_session_and_keeps_it(self):
        log = EVSessionLog()
        _charge(log, EVENING, kwh=7.0, cost=0.7)
        assert log.current is None
        assert log.plugged_in is False
        assert log.latest is log.recent[0]
        assert log.recent[0].end == EVENING + timedelta(minutes=61)

    def test_the_step_that_reads_unplugged_still_counts_its_energy(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        track_session(log, _step(EVENING + timedelta(minutes=1), UNPLUGGED, 0.1, 0.01))
        assert log.recent[0].energy_kwh == pytest.approx(0.1)

    def test_an_unknown_state_neither_starts_nor_ends_a_session(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, UNKNOWN, 1.0, 0.1))
        assert log.current is None
        track_session(log, _step(EVENING, PLUGGED))
        track_session(log, _step(EVENING + timedelta(minutes=1), UNKNOWN, 1.0, 0.1))
        assert log.current is not None
        assert log.current.energy_kwh == pytest.approx(1.0)
        assert log.plugged_in is True

    def test_a_plug_in_that_delivers_nothing_is_not_kept(self):
        log = EVSessionLog()
        _charge(log, EVENING, kwh=5.0, cost=0.5)
        _charge(log, EVENING + timedelta(days=1), kwh=0.0, cost=0.0)
        assert len(log.recent) == 1
        assert log.latest.energy_kwh == pytest.approx(5.0)

    def test_negative_steps_are_not_subtracted(self):
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        track_session(log, _step(EVENING, CHARGING, -1.0, -0.1))
        assert log.current.energy_kwh == 0.0
        assert log.current.cost == 0.0

    def test_the_running_session_is_the_latest(self):
        log = EVSessionLog()
        _charge(log, EVENING)
        track_session(log, _step(EVENING + timedelta(days=1), PLUGGED))
        assert log.latest is log.current


class TestRecentSessions:
    def test_newest_first_and_capped(self):
        log = EVSessionLog()
        starts = [EVENING + timedelta(days=n) for n in range(EV_RECENT_SESSIONS_MAX + 3)]
        for start in starts:
            _charge(log, start)
        assert len(log.recent) == EV_RECENT_SESSIONS_MAX == 10
        assert [s.start for s in log.recent] == starts[::-1][:EV_RECENT_SESSIONS_MAX]

    def test_cost_per_kwh(self):
        assert EVSession(EVENING, energy_kwh=31.6, cost=3.43).per_kwh == pytest.approx(
            0.10854, 1e-3
        )
        assert EVSession(EVENING).per_kwh is None


class TestStorage:
    def test_a_round_trip_keeps_the_running_session_and_the_list(self):
        log = EVSessionLog()
        _charge(log, EVENING, kwh=7.0, cost=0.7)
        track_session(log, _step(EVENING + timedelta(days=1), PLUGGED))
        track_session(log, _step(EVENING + timedelta(days=1, minutes=5), CHARGING, 1.0, 0.1))
        restored = EVSessionLog.from_storage(log.to_storage())
        assert restored == log

    @pytest.mark.parametrize(
        "stored",
        [None, [], "x", {"recent": "x"}, {"recent": [{"start": "not a time"}, 3]}],
    )
    def test_a_damaged_log_starts_empty(self, stored):
        restored = EVSessionLog.from_storage(stored)
        assert restored.current is None
        assert restored.recent == []

    def test_a_damaged_entry_is_skipped_and_the_rest_kept(self):
        log = EVSessionLog()
        _charge(log, EVENING)
        stored = log.to_storage()
        stored["recent"].insert(0, {"start": "garbage"})
        assert EVSessionLog.from_storage(stored).recent == log.recent

    def test_an_empty_log_is_empty(self):
        assert EVSessionLog().is_empty
        log = EVSessionLog()
        track_session(log, _step(EVENING, PLUGGED))
        assert not log.is_empty


class TestRecentTable:
    def test_the_table_reads_like_the_dashboard_expects(self):
        night = EVSession(
            start=datetime(2031, 10, 15, 23, 10),
            end=datetime(2031, 10, 16, 6, 40),
            energy_kwh=31.6,
            cost=3.43,
        )
        sunny = EVSession(
            start=datetime(2031, 10, 12, 12, 20),
            end=datetime(2031, 10, 12, 15, 5),
            energy_kwh=6.9,
            cost=0.0,
        )
        assert recent_table([night, sunny], "€") == (
            "| Charge | Energy | Cost | Per kWh |\n"
            "|:--|--:|--:|--:|\n"
            "| 15 Oct, 23:10 to 06:40 | 31.6 kWh | €3.43 | €0.109 |\n"
            "| 12 Oct, 12:20 to 15:05 | 6.9 kWh | €0.00 | solar |"
        )

    def test_no_finished_sessions_is_one_sentence(self):
        assert recent_table([], "£") == NO_FINISHED_SESSIONS == "No finished charges yet."

    def test_a_session_longer_than_a_day_names_the_end_day(self):
        long = EVSession(
            start=datetime(2031, 1, 1, 9, 0),
            end=datetime(2031, 1, 3, 8, 0),
            energy_kwh=2.0,
            cost=0.5,
        )
        assert "| 1 Jan, 09:00 to 3 Jan, 08:00 | 2.0 kWh | £0.50 | £0.250 |" in recent_table(
            [long], "£"
        )
