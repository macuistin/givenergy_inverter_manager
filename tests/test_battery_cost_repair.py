"""The repair that asks for the battery cost once the integration has run for a while."""

from __future__ import annotations

from datetime import timedelta

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import (
    BATTERY_LIFE_ESTIMATE_MIN_DAYS,
    CONF_BATTERY_COST,
)
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_BATTERY_COST_NOT_SET,
    LEARN_MORE_URLS,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _coord(**cfg_overrides) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**cfg_overrides))
    coord.set_states(_default_states())
    return coord


def _raised() -> list[dict]:
    return [
        c.kwargs
        for c in ir.async_create_issue.call_args_list
        if c.args[2] == ISSUE_BATTERY_COST_NOT_SET
    ]


def _cleared() -> int:
    return sum(
        1 for c in ir.async_delete_issue.call_args_list if c.args[2] == ISSUE_BATTERY_COST_NOT_SET
    )


def _run_for(coord: FakeCoordinator, days: int) -> None:
    """Make the integration look as if it had been tracking the battery for *days* days."""
    coord._battery_stats.tracking_start_date = coord._now().date() - timedelta(days=days)


@pytest.mark.asyncio
async def test_a_zero_cost_after_a_week_raises_a_fixable_warning():
    coord = _coord()
    _run_for(coord, BATTERY_LIFE_ESTIMATE_MIN_DAYS)

    await coord._async_update_data()

    (issue,) = _raised()
    assert issue["is_fixable"] is True
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == ISSUE_BATTERY_COST_NOT_SET
    assert issue["learn_more_url"] == LEARN_MORE_URLS[ISSUE_BATTERY_COST_NOT_SET]
    assert _cleared() == 0


@pytest.mark.asyncio
async def test_a_new_install_is_not_asked_yet():
    coord = _coord()
    _run_for(coord, BATTERY_LIFE_ESTIMATE_MIN_DAYS - 1)

    await coord._async_update_data()

    assert _raised() == []


@pytest.mark.asyncio
async def test_a_set_cost_raises_nothing_and_clears_the_issue():
    coord = _coord(**{CONF_BATTERY_COST: 6500.0})
    _run_for(coord, 30)

    await coord._async_update_data()

    assert _raised() == []
    assert _cleared() >= 1


@pytest.mark.asyncio
async def test_a_cost_saved_in_the_options_counts():
    coord = _coord()
    coord.entry.options = {CONF_BATTERY_COST: 6500.0}
    _run_for(coord, 30)

    await coord._async_update_data()

    assert _raised() == []
