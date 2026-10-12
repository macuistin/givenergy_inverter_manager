"""The charge target is worked out again while the cheap window is open, and a change is written."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.const import CONF_CHARGE_REPLAN, CONF_DRY_RUN
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.sensor_values import overnight_charge_reason
from tests.fakes.fake_inverter import FakeInverter
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

# The test tariff's cheapest period is 02:00 to 04:00: the write fires at 01:59, the late check
# is at 03:00 and nothing is re-planned from 03:45.
TRIGGER = datetime(2031, 3, 4, 1, 59, tzinfo=timezone.utc)
TARGET = "number.target_soc"


class _Clock:
    def __init__(self) -> None:
        self.now = TRIGGER


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: clock.now))
    return clock


def _decision(target: int = 60, *, forecast: float = 10.0, skip: bool = False, ev: bool = False):
    return ChargeDecision(
        target_soc=target,
        skip_charge=skip,
        reason="the normal plan",
        forecast_kwh=forecast,
        current_soc=40.0,
        battery_capacity=19.0,
        car_plugged_in=ev,
        cost_to_charge=1.0,
    )


def _coord(*, replan: bool = True, **cfg) -> tuple[FakeCoordinator, FakeInverter]:
    coord = FakeCoordinator(cfg=_cfg(**{CONF_CHARGE_REPLAN: replan, **cfg}))
    coord.set_states(_default_states())
    backend = FakeInverter()
    coord._backend = backend
    coord.data = MagicMock(charge_decision=_decision(), charge_window=None)
    return coord, backend


async def _settle(coord: FakeCoordinator) -> None:
    while coord.tasks_created:
        await coord.tasks_created.pop(0)


async def _first_write(coord: FakeCoordinator) -> None:
    coord._write_charge_target_to_inverter(coord._now())
    await _settle(coord)


async def _check(coord: FakeCoordinator, clock: _Clock, hour: int, minute: int = 0, **new) -> None:
    """Move the clock, put a new decision in the snapshot and run one cycle's check."""
    clock.now = TRIGGER.replace(hour=hour, minute=minute)
    if new:
        coord.data.charge_decision = replace(coord.data.charge_decision, **new)
    coord._maybe_replan(coord.data, clock.now)
    await _settle(coord)


def _notes(coord: FakeCoordinator) -> list[dict]:
    return [e for e in coord._acc.state.register_write_log if e["reason"] == "replan"]


class TestWhenItIsOff:
    async def test_nothing_is_re_planned_by_default(self, clock):
        coord, backend = _coord(replan=False)
        await _first_write(coord)

        await _check(coord, clock, 3, target_soc=90)

        assert len(backend.plans) == 1
        assert _notes(coord) == []


class TestTheLateCheck:
    async def test_a_target_that_moved_is_written_into_the_same_window(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        first = backend.plans[0]

        await _check(coord, clock, 3, target_soc=75)

        assert len(backend.plans) == 2
        second = backend.plans[1]
        assert second.target_soc == 75
        assert (second.window_start, second.window_end) == (first.window_start, first.window_end)
        assert backend.target_soc == 75

    async def test_it_says_so_on_the_reason_sensor_and_in_the_log(self, clock):
        coord, _ = _coord()
        await _first_write(coord)

        await _check(coord, clock, 3, target_soc=75)
        coord._maybe_replan(coord.data, clock.now)

        assert coord.data.charge_replan_note.startswith("Re-planned at 03:00: ")
        [note] = _notes(coord)
        assert note["entity_id"] == TARGET
        assert note["value"].startswith("60% to 75%")

    async def test_the_sensor_leads_with_the_note_and_keeps_the_plan_reason(self):
        data = MagicMock()
        data.published_charge_decision = _decision()
        data.charge_replan_note = "Re-planned at 03:00: the forecast fell by 20%."
        assert overnight_charge_reason(data) == (
            "Re-planned at 03:00: the forecast fell by 20%. the normal plan"
        )
        data.charge_replan_note = ""
        assert overnight_charge_reason(data) == "the normal plan"

    async def test_a_move_under_five_points_is_left_alone(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 3, target_soc=63)

        assert len(backend.plans) == 1
        assert _notes(coord) == []

    async def test_it_checks_once(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        await _check(coord, clock, 3, target_soc=62)

        await _check(coord, clock, 3, 10, target_soc=90)

        assert len(backend.plans) == 1

    async def test_a_target_of_a_hundred_turns_the_enable_switch_off(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 3, target_soc=100)

        assert backend.plans[-1].target_soc == 100
        assert backend.plans[-1].enable_charge_target is False


class TestTheOtherTriggers:
    async def test_a_forecast_that_fell_is_re_planned_before_the_late_check(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 2, 30, target_soc=80, forecast_kwh=7.0)

        assert backend.plans[-1].target_soc == 80
        assert "the forecast fell by 30%" in _notes(coord)[0]["value"]

    async def test_a_small_forecast_move_is_not_a_trigger(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 2, 30, target_soc=80, forecast_kwh=9.0)

        assert len(backend.plans) == 1

    async def test_a_car_plugged_in_is_re_planned(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 2, 30, target_soc=70, car_plugged_in=True)

        assert backend.plans[-1].target_soc == 70
        assert "the car was plugged in" in _notes(coord)[0]["value"]


class TestTheLimits:
    async def test_three_re_plans_a_night_and_no_more(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        for minute, target, forecast in [(10, 70, 7.0), (20, 80, 5.0), (30, 90, 3.0), (40, 99, 1.0)]:
            await _check(coord, clock, 2, minute, target_soc=target, forecast_kwh=forecast)

        assert [p.target_soc for p in backend.plans] == [60, 70, 80, 90]
        assert len(_notes(coord)) == 3

    async def test_re_plans_before_a_restart_still_count(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        for minute, target in [(10, 70), (20, 80), (30, 90)]:
            await _check(coord, clock, 2, minute, target_soc=target, forecast_kwh=10.0 - minute / 5)

        # A restart loses what the coordinator remembers of the night, but not the write log.
        coord._night.replans = 0
        coord._night.late_check_done = False
        await _check(coord, clock, 3, target_soc=50, forecast_kwh=1.0)

        assert len(_notes(coord)) == 3

    async def test_a_manual_override_stops_it(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        coord.override_charge_enabled = True

        await _check(coord, clock, 3, target_soc=90)

        assert len(backend.plans) == 1

    async def test_nothing_is_written_with_too_little_window_left(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 3, 50, target_soc=90, forecast_kwh=2.0)

        assert len(backend.plans) == 1

    async def test_nothing_is_written_after_the_window(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 4, 30, target_soc=90, forecast_kwh=2.0)

        assert len(backend.plans) == 1

    async def test_a_skip_is_not_taken_once_a_charge_was_written(self, clock):
        coord, backend = _coord()
        await _first_write(coord)

        await _check(coord, clock, 3, skip_charge=True, target_soc=10)

        assert len(backend.plans) == 1

    async def test_a_skipped_night_that_now_needs_a_charge_is_written(self, clock):
        coord, backend = _coord()
        coord.data.charge_decision = _decision(skip=True)
        await _first_write(coord)
        assert backend.plans[0].target_soc == 10

        await _check(coord, clock, 3, skip_charge=False, target_soc=60)

        assert backend.plans[-1].target_soc == 60

    async def test_with_no_write_tonight_there_is_nothing_to_compare_with(self, clock):
        coord, backend = _coord()

        await _check(coord, clock, 3, target_soc=90)

        assert backend.plans == []

    async def test_the_next_nights_write_starts_fresh(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        await _check(coord, clock, 3, target_soc=75)
        assert coord._replan_note

        clock.now = TRIGGER + timedelta(days=1)
        await _first_write(coord)

        assert coord._replan_note == ""
        assert coord._night.replans == 0
        assert coord._night.target == 75

    async def test_a_second_check_before_the_first_write_ends_sends_one(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        clock.now = TRIGGER.replace(hour=3, minute=0)
        coord.data.charge_decision = replace(coord.data.charge_decision, target_soc=75)

        coord._maybe_replan(coord.data, clock.now)
        coord._maybe_replan(coord.data, clock.now)
        await _settle(coord)

        assert len(backend.plans) == 2
        assert len(_notes(coord)) == 1


class TestWhenTheInverterDoesNotTakeIt:
    async def test_the_old_target_stands_and_nothing_is_said_on_the_sensor(self, clock):
        coord, backend = _coord()
        await _first_write(coord)
        backend.fail_target = True

        await _check(coord, clock, 3, target_soc=75)

        assert coord._night.target == 60
        assert coord._replan_note == ""
        assert coord.scheduled == []


class TestDryRun:
    async def test_it_records_one_would_re_plan_and_sends_nothing(self, clock):
        coord, backend = _coord(**{CONF_DRY_RUN: True})
        await _first_write(coord)

        await _check(coord, clock, 3, target_soc=75)
        await _check(coord, clock, 3, 5, target_soc=75)

        assert backend.plans == []
        assert coord._dry_run_last_skipped.startswith("Would re-plan the charge target from 60% to 75%")
        assert _notes(coord) == []

    async def test_dry_run_still_stops_at_three(self, clock):
        coord, _ = _coord(**{CONF_DRY_RUN: True})
        await _first_write(coord)

        for minute, target, forecast in [(10, 70, 7.0), (20, 80, 5.0), (30, 90, 3.0), (40, 99, 1.0)]:
            await _check(coord, clock, 2, minute, target_soc=target, forecast_kwh=forecast)

        assert coord._night.replans == 3
        assert coord._night.target == 90
