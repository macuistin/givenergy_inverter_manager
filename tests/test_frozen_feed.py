"""A GivTCP feed that holds its last values is treated like a silent one."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.givenergy_inverter_manager.const import GIVTCP_FROZEN_AFTER_S
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.lib.givtcp.writer import GivTCPWriter
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_GIVTCP_FEED_FROZEN,
    LEARN_MORE_URLS,
)
from tests.test_coordinator import FakeCoordinator, FakeState, _cfg, _default_states

START = datetime(2031, 3, 4, 22, 51, tzinfo=timezone.utc)
STEP = timedelta(seconds=30)
LIMIT = timedelta(seconds=GIVTCP_FROZEN_AFTER_S)
FEED = ("sensor.solar", "sensor.battery_soc", "sensor.battery_power", "sensor.grid", "sensor.house")


class _Clock:
    def __init__(self) -> None:
        self.now = START

    def advance(self, by: timedelta) -> None:
        self.now += by


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: clock.now))
    return clock


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _publish(coord: FakeCoordinator, clock: _Clock, *entities: str) -> None:
    """GivTCP publishes these entities now. The value need not change."""
    for entity_id in entities or FEED:
        coord._states[entity_id] = FakeState(
            coord._states[entity_id].state, last_reported=clock.now
        )


def _coord(clock: _Clock, **cfg) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**cfg))
    coord.set_states(_default_states())
    _publish(coord, clock)
    return coord


async def _cycles(coord, clock, span: timedelta, *, publishing: bool) -> None:
    """Run cycles every 30 s for `span`, with GivTCP publishing or not. A failed cycle is fine."""
    elapsed = timedelta(0)
    while elapsed < span:
        clock.advance(STEP)
        elapsed += STEP
        if publishing:
            _publish(coord, clock)
        try:
            await coord._async_update_data()
        except UpdateFailed:
            pass


def _frozen_issues() -> list:
    return [c for c in ir.async_create_issue.call_args_list if c.args[2] == ISSUE_GIVTCP_FEED_FROZEN]


class TestDetection:
    async def test_a_steady_but_still_publishing_feed_never_trips(self, clock, caplog):
        coord = _coord(clock)
        with caplog.at_level(logging.WARNING):
            # Hours of the same values, each one reported again every cycle.
            await _cycles(coord, clock, timedelta(hours=3), publishing=True)
        assert coord._givtcp_frozen is False
        assert _frozen_issues() == []
        assert not any("frozen" in r.message for r in caplog.records)

    async def test_a_hiccup_shorter_than_the_limit_does_not_trip(self, clock):
        coord = _coord(clock)
        await _cycles(coord, clock, LIMIT - STEP, publishing=False)
        assert coord._givtcp_frozen is False
        assert await coord._async_update_data() is not None

    async def test_a_feed_that_stops_trips_past_the_limit_with_the_frozen_message(self, clock):
        coord = _coord(clock)
        clock.advance(LIMIT + STEP)
        with pytest.raises(UpdateFailed) as failed:
            await coord._async_update_data()
        assert failed.value.translation_key == "givtcp_frozen"
        assert coord._givtcp_frozen is True

    async def test_it_warns_once_that_the_feed_is_frozen_not_unavailable(self, clock, caplog):
        coord = _coord(clock)
        with caplog.at_level(logging.WARNING):
            await _cycles(coord, clock, LIMIT + 10 * STEP, publishing=False)
        warnings = [r.message for r in caplog.records if "frozen" in r.message]
        assert len(warnings) == 1
        assert "not unavailable" in warnings[0]

    async def test_it_raises_one_repair_that_links_to_troubleshooting(self, clock):
        coord = _coord(clock)
        await _cycles(coord, clock, LIMIT + 10 * STEP, publishing=False)
        [issue] = _frozen_issues()
        assert issue.kwargs["is_fixable"] is False
        assert issue.kwargs["learn_more_url"] == LEARN_MORE_URLS[ISSUE_GIVTCP_FEED_FROZEN]
        assert issue.kwargs["translation_placeholders"] == {"last_reported": "04 Mar 22:51"}

    async def test_it_clears_and_says_so_when_the_feed_moves_again(self, clock, caplog):
        coord = _coord(clock)
        await _cycles(coord, clock, LIMIT + 2 * STEP, publishing=False)
        ir.async_delete_issue.reset_mock()

        _publish(coord, clock)
        with caplog.at_level(logging.INFO):
            data = await coord._async_update_data()

        assert data is not None
        assert coord._givtcp_frozen is False
        assert any(c.args[2] == ISSUE_GIVTCP_FEED_FROZEN for c in ir.async_delete_issue.call_args_list)
        assert any("reporting again" in r.message for r in caplog.records)

    async def test_one_entity_still_reporting_keeps_the_feed_alive(self, clock):
        coord = _coord(clock)
        for _ in range(int(LIMIT.total_seconds() // 30) * 2):
            clock.advance(STEP)
            _publish(coord, clock, "sensor.house")  # only the load keeps reporting
        assert await coord._async_update_data() is not None
        assert coord._givtcp_frozen is False

    async def test_entities_that_are_not_configured_or_missing_are_left_out(self, clock):
        coord = _coord(clock)
        del coord._states["sensor.house"]
        del coord._states["sensor.grid"]
        clock.advance(LIMIT + STEP)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    async def test_a_feed_with_nothing_to_judge_is_the_silent_checks_case(self, clock):
        coord = FakeCoordinator(cfg=_cfg())
        with pytest.raises(UpdateFailed) as failed:
            await coord._async_update_data()
        assert failed.value.translation_key == "givtcp_unavailable"
        assert coord._givtcp_frozen is False


class TestWhileFrozen:
    async def test_the_cycle_does_not_run_so_nothing_is_planned_or_written(self, clock):
        coord = _coord(clock)
        await coord._async_update_data()
        clock.advance(LIMIT + STEP)
        coord.service_calls.clear()

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

        assert coord.service_calls == []

    def _decision(self, coord) -> None:
        coord.data = type("Data", (), {})()
        coord.data.charge_decision = ChargeDecision(
            target_soc=75,
            skip_charge=False,
            reason="planned from the frozen 4%",
            forecast_kwh=10.0,
            current_soc=4.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        coord.data.charge_window = None

    async def test_the_nightly_write_is_skipped_while_frozen(self, clock, caplog):
        coord = _coord(clock)
        await coord._async_update_data()
        await _cycles(coord, clock, LIMIT + 2 * STEP, publishing=False)
        self._decision(coord)

        with caplog.at_level(logging.WARNING):
            coord._write_charge_target_to_inverter(clock.now)

        assert coord.tasks_created == []
        assert coord.service_calls == []
        assert any("not written" in r.message for r in caplog.records)

    async def test_the_nightly_write_goes_ahead_when_the_feed_is_live(self, clock):
        coord = _coord(clock)
        await coord._async_update_data()
        self._decision(coord)

        coord._write_charge_target_to_inverter(clock.now)

        assert len(coord.tasks_created) == 1
        await coord.tasks_created[0]
        assert coord.service_calls_for("number", "set_value")[0]["value"] == 75

    async def test_the_nightly_write_resumes_once_the_feed_does(self, clock):
        coord = _coord(clock)
        await _cycles(coord, clock, LIMIT + 2 * STEP, publishing=False)
        _publish(coord, clock)
        await coord._async_update_data()
        self._decision(coord)

        coord._write_charge_target_to_inverter(clock.now)

        assert len(coord.tasks_created) == 1
        coord.tasks_created[0].close()

    async def test_the_held_charge_plan_survives_and_is_still_there_after(self, clock):
        coord = _coord(clock)
        await coord._async_update_data()
        held = coord._held_charge.decision
        window = coord._held_charge.window
        assert held is not None

        await _cycles(coord, clock, LIMIT + 10 * STEP, publishing=False)
        assert coord._held_charge.decision is held
        assert coord._held_charge.window is window

        _publish(coord, clock)
        await coord._async_update_data()
        assert coord._held_charge.decision is not None

    async def test_energy_is_not_added_across_the_gap(self, clock):
        coord = _coord(clock)
        await coord._async_update_data()
        await _cycles(coord, clock, LIMIT + 2 * STEP, publishing=False)
        assert coord._last_update is None

    async def test_dry_run_trips_the_same_way(self, clock):
        coord = _coord(clock, dry_run=True)
        assert coord.is_dry_run is True
        await _cycles(coord, clock, LIMIT + 2 * STEP, publishing=False)
        assert coord._givtcp_frozen is True
        assert len(_frozen_issues()) == 1

