"""A skip needs the simulated day to hold, and the plan text follows a charge past the cheap rate."""

from __future__ import annotations

from datetime import datetime, time

from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow
from custom_components.givenergy_inverter_manager.core.engine import (
    CoordinatorData,
    _charge_running,
    _in_planned_window,
)
from custom_components.givenergy_inverter_manager.core.reporting import (
    build_charge_plan_state,
    shown_charge_decision,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeDecision,
    monthly_solar_fractions,
)
from tests.conftest import _raw
from tests.core.flat_rules import calculate_overnight_charge_target


def _plan(*, load_kwh: float, forecast_kwh: float = 14.0, soc: float = 90.0):
    return calculate_overnight_charge_target(
        current_soc=soc,
        battery_capacity_kwh=10.0,
        forecast_kwh=forecast_kwh,
        inverter_max_kw=5.0,
        car_plugged_in=False,
        min_soc=10,
        skip_charge_threshold=75,
        average_daily_consumption_kwh=load_kwh,
        cheapest_rate=0.1,
        solar_fractions=monthly_solar_fractions(53.3),
        dt=datetime(2026, 6, 15, 22, 0),
    )


class TestTheSimulatedDayJudgesTheSkip:
    def test_a_day_the_battery_holds_skips(self):
        assert _plan(load_kwh=6.0).skip_charge is True

    def test_a_day_that_empties_the_battery_does_not_skip_and_says_why(self):
        decision = _plan(load_kwh=40.0)
        assert decision.skip_charge is False
        assert "Not skipping" in decision.reason


def _window(start: time, end: time) -> ChargeWindow:
    return ChargeWindow(start, end, extended=True, expected_kwh=None, finish_time=None)


class TestAChargePastTheCheapRateIsStillTheCharge:
    def test_inside_a_window_that_crosses_midnight(self):
        held = HeldCharge(window=_window(time(23, 0), time(2, 0)))
        assert _in_planned_window(held, datetime(2026, 11, 2, 23, 30))
        assert _in_planned_window(held, datetime(2026, 11, 2, 1, 0))
        assert not _in_planned_window(held, datetime(2026, 11, 2, 2, 0))

    def test_no_window_is_never_inside(self):
        assert not _in_planned_window(HeldCharge(), datetime(2026, 11, 2, 5, 0))

    def test_grid_charging_after_the_cheap_run_counts_inside_the_window(self):
        held = HeldCharge(window=_window(time(2, 0), time(6, 0)))
        data = CoordinatorData()  # no cheap run left
        raw = _raw(battery_power_w=3000.0, grid_power_w=3200.0)
        assert _charge_running(data, raw, held, datetime(2026, 11, 2, 4, 39))
        assert not _charge_running(data, raw, HeldCharge(), datetime(2026, 11, 2, 4, 39))


class TestThePlanTextFollowsThePublishedDecision:
    @staticmethod
    def _decision(skip: bool) -> ChargeDecision:
        return ChargeDecision(80, skip, "r", 10.0, 76.0, 19.0, False, 0.5)

    def test_a_fresh_skip_does_not_replace_the_held_charge_in_the_text(self):
        data = CoordinatorData()
        data.charge_decision = self._decision(True)
        data.published_charge_decision = self._decision(False)
        assert shown_charge_decision(data) is data.published_charge_decision
        assert build_charge_plan_state(data).startswith("Target 80%")

    def test_the_fresh_decision_is_used_before_one_is_published(self):
        data = CoordinatorData()
        data.charge_decision = self._decision(True)
        assert build_charge_plan_state(data).startswith("Skip charge")
