"""The repair that asks for the battery cost waits until the integration has run a while."""

from __future__ import annotations

from datetime import timedelta

from custom_components.givenergy_inverter_manager.const import BATTERY_LIFE_ESTIMATE_MIN_DAYS
from custom_components.givenergy_inverter_manager.core.battery import (
    BatteryStats,
    battery_cost_prompt_due,
)
from tests.core.flat_battery import FROZEN_TODAY

TODAY = FROZEN_TODAY


def _stats(days_tracked: int) -> BatteryStats:
    return BatteryStats(tracking_start_date=TODAY - timedelta(days=days_tracked))


def test_due_when_the_cost_is_zero_after_enough_days():
    assert battery_cost_prompt_due(0.0, _stats(BATTERY_LIFE_ESTIMATE_MIN_DAYS), TODAY) is True


def test_not_due_the_day_before_enough_days_have_passed():
    assert battery_cost_prompt_due(0.0, _stats(BATTERY_LIFE_ESTIMATE_MIN_DAYS - 1), TODAY) is False


def test_not_due_before_tracking_has_started():
    assert battery_cost_prompt_due(0.0, BatteryStats(), TODAY) is False


def test_not_due_once_a_cost_is_set():
    assert battery_cost_prompt_due(6500.0, _stats(30), TODAY) is False
