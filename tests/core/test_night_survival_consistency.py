"""Night survival and tonight's charge plan must use the same window and agree."""

from datetime import datetime
from itertools import product

import pytest

from custom_components.givenergy_inverter_manager.accumulation import EnergyAccumulator
from custom_components.givenergy_inverter_manager.core.battery import hours_until_solar
from tests.conftest import _nightboost_cfg, _raw, _run
from tests.core.flat_rules import calculate_overnight_charge_target


class TestHoursUntilSolar:
    @pytest.mark.parametrize(
        ("hour", "solar", "expected"),
        [
            (2, False, 6.0),  # live night: hours left to 08:00
            (7, False, 1.0),
            (7, True, 1.0),  # early solar noise does not change a live night
            (11, True, 8.0),  # midday: tonight's pre-solar window, not 21 h
            (11, False, 21.0),  # no generation after sunrise: from now to sunrise
            (20, False, 12.0),
        ],
    )
    def test_window(self, hour, solar, expected):
        assert hours_until_solar(hour, solar) == expected


def _plan_and_survival(*, now, soc, capacity, avg_daily, forecast, solar_w):
    acc = EnergyAccumulator()
    acc.house_kwh = avg_daily * (now.hour * 60 + now.minute) / 1440
    cfg = _nightboost_cfg()
    cfg["battery_capacity_kwh"] = capacity
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=capacity,
        solar_power_w=solar_w,
        forecast_kwh_tomorrow=forecast,
    )
    data, _ = _run(raw=raw, cfg=cfg, now=now, acc=acc)
    return data


class TestLiveCase:
    def test_midday_good_forecast_skips_and_survives(self):
        """Oct 5, 11:12, SoC 89%, 19.05 kWh, 9 kWh used so far, 6.5 kWh forecast."""
        data = _plan_and_survival(
            now=datetime(2026, 10, 5, 11, 12),
            soc=89.0,
            capacity=19.05,
            avg_daily=9.0 * 1440 / (11 * 60 + 12),
            forecast=6.5,
            solar_w=3000.0,
        )
        assert data.charge_decision.skip_charge is True
        assert data.will_survive_night is True
        assert "Battery should last" in data.survival_reason

    def test_after_dark_a_real_shortfall_is_still_reported(self):
        """At 20:00 with no solar the window is 12 h. A small battery is Critical."""
        data = _plan_and_survival(
            now=datetime(2026, 6, 15, 20, 0),
            soc=60.0,
            capacity=10.0,
            avg_daily=24.0,
            forecast=15.0,
            solar_w=0.0,
        )
        assert data.will_survive_night is False
        assert data.charge_decision.skip_charge is False


class TestSkipNeedsSurvival:
    def _kwargs(self, **overrides):
        base = {
            "current_soc": 80.0,
            "battery_capacity_kwh": 5.0,
            "forecast_kwh": 15.0,
            "inverter_max_kw": 5.0,
            "car_plugged_in": False,
            "min_soc": 10,
            "skip_charge_threshold": 75,
            "average_daily_consumption_kwh": 30.0,
            "cheapest_rate": 0.1,
            "dt": datetime(2026, 6, 15, 23, 0),
            "solar_generating": False,
        }
        base.update(overrides)
        return base

    def test_small_battery_that_cannot_reach_sunrise_does_not_skip(self):
        decision = calculate_overnight_charge_target(**self._kwargs())
        assert decision.skip_charge is False
        assert "Not skipping" in decision.reason
        assert "shortfall" in decision.reason

    def test_battery_that_reaches_sunrise_still_skips(self):
        decision = calculate_overnight_charge_target(
            **self._kwargs(battery_capacity_kwh=19.0, average_daily_consumption_kwh=15.0)
        )
        assert decision.skip_charge is True


@pytest.mark.parametrize(
    ("hour", "solar_w", "soc", "capacity", "avg_daily"),
    list(
        product(
            (1, 6, 11, 16, 20, 23),
            (0.0, 2500.0),
            (75.0, 80.0, 89.0, 100.0),
            (5.0, 10.0, 19.05),
            (10.0, 20.0, 40.0),
        )
    ),
)
def test_plan_never_skips_when_survival_is_critical(hour, solar_w, soc, capacity, avg_daily):
    """Invariant: skip_charge implies will_survive_night, in every summer scenario."""
    data = _plan_and_survival(
        now=datetime(2026, 6, 15, hour, 0),
        soc=soc,
        capacity=capacity,
        avg_daily=avg_daily,
        forecast=15.0,
        solar_w=solar_w,
    )
    if data.charge_decision.skip_charge:
        assert data.will_survive_night, data.survival_reason
