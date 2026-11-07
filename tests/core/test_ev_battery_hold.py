"""When to hold the house battery back for the car, and what a hold writes."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.ev_battery_hold import (
    HoldFacts,
    HoldRecord,
    HoldStep,
    decide_hold,
    hold_ends,
    hold_window,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.model import (
    BatteryPause,
    PauseSetting,
)

NOW = datetime(2031, 3, 4, 10, 17, 40, tzinfo=timezone.utc)
OFF = PauseSetting(BatteryPause.OFF)
NIGHT = PauseSetting(BatteryPause.DISCHARGE, (time(23, 0), time(8, 0)))


def _facts(**overrides) -> HoldFacts:
    base = {
        "enabled": True,
        "car_draining_battery": True,
        "minutes_since_car_charged": None,
        "now": NOW,
        "live": OFF,
    }
    base.update(overrides)
    return HoldFacts(**base)


# ── Starting ──────────────────────────────────────────────────────────────────


def test_a_car_draining_the_battery_with_no_pause_starts_a_hold():
    assert decide_hold(_facts()).step is HoldStep.START


def test_a_night_pause_that_is_not_running_now_does_not_stop_a_hold():
    assert decide_hold(_facts(live=NIGHT)).step is HoldStep.START


def test_nothing_starts_with_the_switch_off():
    assert decide_hold(_facts(enabled=False)).step is HoldStep.NOTHING


def test_nothing_starts_while_the_car_is_not_draining_the_battery():
    assert decide_hold(_facts(car_draining_battery=False)).step is HoldStep.NOTHING


def test_a_pause_already_covering_now_is_left_alone():
    night = _facts(now=NOW.replace(hour=2), live=NIGHT)

    decision = decide_hold(night)

    assert decision.step is HoldStep.NOTHING
    assert "already paused" in decision.note


@pytest.mark.parametrize("pause", [BatteryPause.CHARGE, BatteryPause.BOTH])
def test_a_pause_that_stops_charging_is_never_touched(pause):
    decision = decide_hold(_facts(live=PauseSetting(pause, (time(1, 0), time(2, 0)))))

    assert decision.step is HoldStep.NOTHING
    assert "stops charging" in decision.note


def test_a_pause_whose_window_cannot_be_read_is_never_overwritten():
    decision = decide_hold(_facts(live=PauseSetting(BatteryPause.DISCHARGE, None)))

    assert decision.step is HoldStep.NOTHING
    assert "cannot be read" in decision.note


def test_an_unreadable_pause_starts_nothing():
    decision = decide_hold(_facts(live=None))

    assert decision.step is HoldStep.NOTHING
    assert "cannot be read" in decision.note


# ── Holding ───────────────────────────────────────────────────────────────────


def test_a_hold_with_time_left_does_nothing_while_the_car_charges():
    held = _facts(holding=True, live=None, hold_ends=NOW + timedelta(minutes=25))

    assert decide_hold(held).step is HoldStep.NOTHING


def test_a_hold_is_renewed_when_ten_minutes_are_left():
    held = _facts(holding=True, live=None, hold_ends=NOW + timedelta(minutes=10))

    assert decide_hold(held).step is HoldStep.RENEW


def test_a_hold_with_no_end_time_is_renewed():
    assert decide_hold(_facts(holding=True, live=None)).step is HoldStep.RENEW


def test_a_hold_ends_with_the_switch():
    held = _facts(enabled=False, holding=True, hold_ends=NOW + timedelta(minutes=25))

    assert decide_hold(held).step is HoldStep.RELEASE


def test_a_short_gap_in_charging_keeps_the_hold():
    held = _facts(holding=True, minutes_since_car_charged=4.0, hold_ends=NOW + timedelta(minutes=25))

    assert decide_hold(held).step is HoldStep.NOTHING


def test_a_car_that_stays_off_for_five_minutes_ends_the_hold():
    held = _facts(holding=True, minutes_since_car_charged=5.0, hold_ends=NOW + timedelta(minutes=25))

    assert decide_hold(held).step is HoldStep.RELEASE


# ── The window ────────────────────────────────────────────────────────────────


def test_a_hold_runs_from_the_last_five_minutes_for_half_an_hour():
    assert hold_window(NOW) == (time(10, 15), time(10, 45))
    assert hold_ends(NOW) == NOW.replace(minute=45, second=0)


def test_a_hold_window_can_cross_midnight():
    late = NOW.replace(hour=23, minute=41)

    assert hold_window(late) == (time(23, 40), time(0, 10))


# ── The saved record ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("prior", [OFF, NIGHT])
def test_a_record_survives_being_saved_and_read(prior):
    record = HoldRecord(prior, NOW)

    assert HoldRecord.from_dict(record.as_dict()) == record


@pytest.mark.parametrize(
    "raw",
    [None, {}, "text", {"pause": "Nonsense", "ends": NOW.isoformat()}, {"pause": "Disabled"}],
)
def test_a_record_that_is_not_whole_reads_as_none(raw):
    assert HoldRecord.from_dict(raw) is None
