"""The coordinator decides what to write and hands it to the backend, which does the writing."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from unittest.mock import MagicMock

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_MIN_SOC,
    CONF_DRY_RUN,
    DEFAULT_BATTERY_MIN_SOC,
)
from custom_components.givenergy_inverter_manager.core.inverter_values import (
    FeedState,
    FeedStatus,
    InverterValues,
)
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.repairs import ISSUE_GIVTCP_NOT_ANSWERING
from tests.fakes.fake_inverter import FakeInverter
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

_NIGHT_START, _NIGHT_END = time(2, 0), time(4, 0)  # the cheapest period in the test tariff


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _coord(*, dry_run: bool = False, skip: bool = False, target: int = 80) -> tuple:
    cfg = _cfg(**{CONF_DRY_RUN: dry_run})
    coord = FakeCoordinator(cfg=cfg)
    coord.set_states(_default_states())
    backend = FakeInverter()
    coord._backend = backend
    data = MagicMock()
    data.charge_decision = ChargeDecision(
        target_soc=target,
        skip_charge=skip,
        reason="test",
        forecast_kwh=10.0,
        current_soc=60.0,
        battery_capacity=19.0,
        car_plugged_in=False,
        cost_to_charge=1.0,
    )
    data.charge_window = None
    coord.data = data
    return coord, backend


async def _run_write(coord) -> None:
    coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
    for task in coord.tasks_created:
        await task


class TestChargeWrite:
    async def test_the_backend_gets_one_plan_with_the_target_and_the_cheapest_window(self):
        coord, backend = _coord(target=75)

        await _run_write(coord)

        [plan] = backend.plans
        assert plan.target_soc == 75
        assert plan.enable_charge_target is True
        assert (plan.window_start, plan.window_end) == (_NIGHT_START, _NIGHT_END)

    async def test_a_skipped_charge_sends_the_minimum_as_the_target(self):
        coord, backend = _coord(skip=True)

        await _run_write(coord)

        [plan] = backend.plans
        assert plan.target_soc == coord._effective_cfg().get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC)

    async def test_a_hundred_percent_target_turns_the_enable_switch_off(self):
        coord, backend = _coord(target=100)

        await _run_write(coord)

        assert backend.plans[0].enable_charge_target is False

    async def test_dry_run_sends_the_backend_nothing(self):
        coord, backend = _coord(dry_run=True)

        await _run_write(coord)

        assert backend.plans == []
        assert backend.floor_targets == []

    async def test_a_frozen_feed_sends_the_backend_nothing(self):
        coord, backend = _coord()
        coord._givtcp_frozen = True

        await _run_write(coord)

        assert backend.plans == []

    async def test_a_feed_that_is_not_answering_sends_the_backend_nothing(self):
        coord, backend = _coord()
        coord._givtcp_not_answering = True

        await _run_write(coord)

        assert backend.plans == []


class TestRead:
    async def test_a_cycle_uses_what_the_backend_read_and_smooths_the_solar_power(self):
        coord, backend = _coord()
        backend.values = InverterValues(solar_power_w=2000.0, battery_soc=55.0, house_load_w=900.0)

        raw = coord._collect_raw(coord._effective_cfg())

        assert (raw.solar_power_w, raw.battery_soc, raw.house_load_w) == (2000.0, 55.0, 900.0)
        assert raw.smoothed_solar_power_w == 1000.0

    async def test_an_unavailable_solar_reading_is_not_fed_into_the_average(self):
        coord, backend = _coord()
        backend.values = InverterValues(unavailable_inputs=("solar_power",))

        raw = coord._collect_raw(coord._effective_cfg())

        assert raw.smoothed_solar_power_w == 0.0
        assert raw.unavailable_inputs == ("solar_power",)


class TestFeed:
    @pytest.mark.parametrize(
        ("state", "key"),
        [
            (FeedState.SILENT, "givtcp_unavailable"),
            (FeedState.MISSING, "givtcp_unavailable"),
            (FeedState.FROZEN, "givtcp_frozen"),
            (FeedState.PAUSED, "givtcp_not_answering"),
            (FeedState.STALE, "givtcp_not_answering"),
        ],
    )
    async def test_each_feed_state_that_is_not_live_fails_the_cycle_with_its_message(
        self, state, key
    ):
        coord, backend = _coord()
        backend.status = FeedStatus(state, datetime.now(timezone.utc) - timedelta(hours=1))

        with pytest.raises(UpdateFailed) as failed:
            await coord._async_update_data()

        assert failed.value.translation_key == key

    @pytest.mark.parametrize("state", [FeedState.PAUSED, FeedState.STALE])
    async def test_a_feed_that_is_not_answering_raises_one_repair_and_one_warning(
        self, state, caplog
    ):
        coord, backend = _coord()
        backend.status = FeedStatus(state)

        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                with pytest.raises(UpdateFailed):
                    await coord._async_update_data()

        created = [c for c in ir.async_create_issue.call_args_list if c.args[2] == ISSUE_GIVTCP_NOT_ANSWERING]
        assert len(created) == 1
        assert created[0].kwargs["is_fixable"] is False
        warnings = [r for r in caplog.records if "not getting data from the inverter" in r.message]
        assert len(warnings) == 1

    async def test_the_repair_clears_when_the_feed_is_live_again(self):
        coord, backend = _coord()
        backend.status = FeedStatus(FeedState.PAUSED)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        ir.async_delete_issue.reset_mock()

        backend.status = FeedStatus(FeedState.PUBLISHING)
        await coord._async_update_data()

        assert coord._givtcp_not_answering is False
        assert any(c.args[2] == ISSUE_GIVTCP_NOT_ANSWERING for c in ir.async_delete_issue.call_args_list)
