"""A nightly charge write that fails is tried again, and a restart inside the window catches up."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, CONF_TARGET_SOC_ENTITY
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from tests.fakes.fake_inverter import FakeInverter
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

# The test tariff's cheapest period is 02:00 to 04:00, so the trigger is 01:59.
START = datetime(2031, 3, 4, 1, 59, tzinfo=timezone.utc)
TARGET = "number.target_soc"


class _Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: clock.now))
    return clock


def _decision(target: int = 80, *, skip: bool = False) -> ChargeDecision:
    return ChargeDecision(
        target_soc=target,
        skip_charge=skip,
        reason="test",
        forecast_kwh=10.0,
        current_soc=60.0,
        battery_capacity=19.0,
        car_plugged_in=False,
        cost_to_charge=1.0,
    )


def _coord(**cfg) -> tuple[FakeCoordinator, FakeInverter]:
    coord = FakeCoordinator(cfg=_cfg(**cfg))
    coord.set_states(_default_states())
    backend = FakeInverter()
    coord._backend = backend
    data = MagicMock()
    data.charge_decision = _decision()
    data.charge_window = None
    coord.data = data
    return coord, backend


async def _settle(coord: FakeCoordinator) -> None:
    """Run every task the coordinator has started."""
    while coord.tasks_created:
        await coord.tasks_created.pop(0)


async def _trigger(coord: FakeCoordinator) -> None:
    coord._write_charge_target_to_inverter(coord._now())
    await _settle(coord)


async def _fire_retry(coord: FakeCoordinator, clock: _Clock) -> None:
    """Move the clock to the pending retry and run it, as Home Assistant would."""
    [(when, action)] = coord.scheduled
    coord.scheduled.clear()
    clock.now = when
    action(when)
    await _settle(coord)


def _log(coord: FakeCoordinator) -> list[dict]:
    return coord._acc.state.register_write_log


def _notes(coord: FakeCoordinator) -> list[str]:
    return [e["value"] for e in _log(coord) if e["reason"] == "retry"]


class TestRetry:
    async def test_a_write_that_works_at_the_trigger_schedules_nothing(self, clock):
        coord, backend = _coord()

        await _trigger(coord)

        assert len(backend.plans) == 1
        assert coord.scheduled == []
        assert _notes(coord) == []

    async def test_a_feed_that_is_down_at_the_trigger_and_up_at_five_minutes_writes_once(
        self, clock
    ):
        coord, backend = _coord()
        coord._givtcp_frozen = True

        await _trigger(coord)
        assert backend.plans == []
        assert [when for when, _ in coord.scheduled] == [START + timedelta(minutes=2)]

        await _fire_retry(coord, clock)  # still down at +2
        assert backend.plans == []
        assert [when for when, _ in coord.scheduled] == [START + timedelta(minutes=5)]

        coord._givtcp_frozen = False
        await _fire_retry(coord, clock)
        assert len(backend.plans) == 1
        assert backend.plans[0].target_soc == 80
        assert coord.scheduled == []

    async def test_a_write_the_inverter_does_not_take_is_tried_again(self, clock):
        coord, backend = _coord()
        backend.fail_target = True

        await _trigger(coord)

        assert len(backend.plans) == 1
        assert [when for when, _ in coord.scheduled] == [START + timedelta(minutes=2)]
        assert "did not take it" in _notes(coord)[0]

        backend.fail_target = False
        await _fire_retry(coord, clock)
        assert len(backend.plans) == 2
        assert backend.target_soc == 80
        assert coord.scheduled == []

    async def test_after_four_failed_retries_it_stops_and_says_so(self, clock):
        coord, backend = _coord()
        backend.fail_target = True

        await _trigger(coord)
        for _ in range(4):
            await _fire_retry(coord, clock)

        assert coord.scheduled == []
        assert len(backend.plans) == 5
        assert _notes(coord)[-1].startswith("gave up after 5 attempts")
        assert _log(coord)[-1]["reason"] == "retry"
        assert _log(coord)[-1]["entity_id"] == TARGET

    async def test_each_failed_attempt_leaves_a_note_in_order(self, clock):
        coord, backend = _coord()
        backend.fail_target = True

        await _trigger(coord)
        await _fire_retry(coord, clock)

        notes = _notes(coord)
        assert notes[0].startswith("attempt 1 failed") and "02:01" in notes[0]
        assert notes[1].startswith("attempt 2 failed") and "02:04" in notes[1]

    async def test_a_manual_override_set_before_the_retry_is_what_gets_written(self, clock):
        coord, backend = _coord()
        backend.fail_target = True
        await _trigger(coord)

        coord.data.charge_decision = _decision(target=95)
        backend.fail_target = False
        await _fire_retry(coord, clock)

        assert backend.plans[-1].target_soc == 95

    async def test_a_skipped_night_retries_with_the_minimum_target(self, clock):
        coord, backend = _coord()
        coord.data.charge_decision = _decision(skip=True)
        backend.fail_target = True

        await _trigger(coord)
        backend.fail_target = False
        await _fire_retry(coord, clock)

        assert [p.target_soc for p in backend.plans] == [10, 10]

    async def test_there_is_no_decision_yet_so_it_waits_and_tries_again(self, clock):
        coord, backend = _coord()
        coord.data = None

        await _trigger(coord)
        assert backend.plans == []
        assert len(coord.scheduled) == 1

        coord.data = MagicMock(charge_decision=_decision(), charge_window=None)
        await _fire_retry(coord, clock)
        assert len(backend.plans) == 1

    async def test_the_next_nights_trigger_cancels_a_pending_retry(self, clock):
        coord, backend = _coord()
        backend.fail_target = True
        await _trigger(coord)
        assert len(coord.scheduled) == 1

        backend.fail_target = False
        await _trigger(coord)

        assert coord.scheduled == []

    async def test_cancelling_removes_the_pending_retry(self, clock):
        coord, backend = _coord()
        backend.fail_target = True
        await _trigger(coord)

        coord._cancel_charge_retry()

        assert coord.scheduled == []

    async def test_a_target_entity_that_is_not_set_is_not_retried(self, clock):
        coord, backend = _coord(**{CONF_TARGET_SOC_ENTITY: ""})

        await _trigger(coord)

        assert backend.plans == [] and coord.scheduled == []


class TestDryRun:
    async def test_dry_run_records_one_would_write_and_sends_nothing(self, clock):
        coord, backend = _coord(**{CONF_DRY_RUN: True})

        await _trigger(coord)

        assert backend.plans == []
        assert coord._dry_run_last_skipped.startswith("Would write charge target 80%")
        assert coord.scheduled == []
        assert _notes(coord) == []


class TestFlatRate:
    async def test_a_flat_rate_tariff_has_no_trigger_no_retry_and_no_catch_up(self, clock):
        coord, backend = _coord(rate_periods=[])
        clock.now = START + timedelta(minutes=30)

        assert coord._charge_target_trigger() is None
        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert backend.plans == [] and coord.scheduled == []


class TestCatchUp:
    async def test_a_restart_inside_the_window_with_no_write_logged_writes_once(self, clock):
        coord, backend = _coord()
        clock.now = START + timedelta(minutes=31)

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert len(backend.plans) == 1

    async def test_a_restart_after_the_window_ends_writes_nothing(self, clock):
        coord, backend = _coord()
        clock.now = START.replace(hour=4, minute=6)

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert backend.plans == []

    async def test_a_restart_with_less_than_fifteen_minutes_left_writes_nothing(self, clock):
        coord, backend = _coord()
        clock.now = START.replace(hour=3, minute=50)

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert backend.plans == []

    async def test_a_restart_before_the_trigger_leaves_it_to_the_listener(self, clock):
        coord, backend = _coord()
        clock.now = START - timedelta(hours=1)

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert backend.plans == []

    async def test_a_write_already_logged_since_the_trigger_is_not_repeated(self, clock):
        coord, backend = _coord()
        clock.now = START + timedelta(minutes=31)
        coord._acc.state.register_write_log = [
            {
                "time": (START + timedelta(minutes=1)).isoformat(),
                "entity_id": TARGET,
                "value": "80",
                "reason": "charge target",
            }
        ]

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert backend.plans == []

    async def test_a_failed_catch_up_schedules_the_remaining_retries(self, clock):
        coord, backend = _coord()
        backend.fail_target = True
        clock.now = START + timedelta(minutes=6)  # +2 and +5 have passed

        await coord.async_catch_up_charge_write()
        await _settle(coord)

        assert [when for when, _ in coord.scheduled] == [START + timedelta(minutes=10)]
