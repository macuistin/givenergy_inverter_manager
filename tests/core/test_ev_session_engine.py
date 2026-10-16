"""The engine prices an EV session exactly as it prices today's EV cost, across midnight too."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    Accumulators,
    CycleInputs,
    ForecastContext,
    PreviousCycle,
    build_coordinator_data,
)
from custom_components.givenergy_inverter_manager.core.ev_session import EVSessionLog
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from tests.conftest import _nightboost_cfg, _raw

CYCLE = timedelta(seconds=30)
CAR_W = 7000.0
HOUSE_W = 500.0


def _charger(state: EVChargerState, power_w: float) -> EVCharger:
    charger = EVCharger(
        brand=EVChargerBrand.ZAPPI, name="Zappi", serial="1", display_name="Zappi", state=state
    )
    charger.power_w = power_w
    return charger


class _House:
    """Runs the real engine cycle after cycle, resetting today at local midnight."""

    def __init__(self, log: EVSessionLog | None) -> None:
        self.log = log
        self.today = EnergyAccumulator()
        self.days: list[EnergyAccumulator] = [self.today]
        self.last: datetime | None = None
        self.stats = BatteryStats()

    def cycle(self, now: datetime, charger: EVCharger | None, *, solar_w: float = 0.0):
        if self.last is not None and now.date() != self.last.date():
            self.today = EnergyAccumulator()
            self.days.append(self.today)
            self.last = None  # as the coordinator's midnight reset does
        ev_w = charger.power_w if charger is not None else 0.0
        load = HOUSE_W + ev_w
        raw = _raw(
            solar_power_w=solar_w,
            house_load_w=load,
            grid_power_w=max(0.0, load - solar_w),
            battery_power_w=0.0,
            ev_power_w=ev_w,
        )
        data, _ = build_coordinator_data(
            CycleInputs(raw=raw, cfg=_nightboost_cfg(), now=now, ev_charger=charger),
            Accumulators(today=self.today, ev_sessions=self.log),
            PreviousCycle(battery_stats=self.stats, last_soc=None, last_update_time=self.last),
            ForecastContext(),
        )
        self.last = now
        return data

    def charge(self, start: datetime, cycles: int, *, solar_w: float = 0.0) -> datetime:
        """Plug in at start, charge for that many cycles, unplug. Returns the unplug time."""
        now = start
        self.cycle(now, _charger(EVChargerState.CONNECTED, 0.0), solar_w=solar_w)
        for _ in range(cycles):
            now += CYCLE
            self.cycle(now, _charger(EVChargerState.CHARGING, CAR_W), solar_w=solar_w)
        now += CYCLE
        self.cycle(now, _charger(EVChargerState.DISCONNECTED, 0.0), solar_w=solar_w)
        return now


def test_a_session_across_midnight_costs_what_the_two_days_ev_cost_counted():
    house = _House(EVSessionLog())
    start = datetime(2031, 10, 15, 23, 10, tzinfo=timezone.utc)
    end = house.charge(start, cycles=240)  # two hours, so it crosses midnight

    session = house.log.recent[0]
    assert len(house.days) == 2
    assert session.start == start
    assert session.end == end
    assert session.cost == pytest.approx(sum(day.zappi_cost for day in house.days))
    assert session.energy_kwh == pytest.approx(sum(day.zappi_kwh for day in house.days))
    assert session.cost > 0


def test_the_snapshot_carries_the_log_the_coordinator_passed():
    log = EVSessionLog()
    house = _House(log)
    data = house.cycle(
        datetime(2031, 10, 15, 12, tzinfo=timezone.utc), _charger(EVChargerState.CONNECTED, 0)
    )
    assert data.ev_sessions is log
    assert log.current is not None


def test_solar_charging_costs_nothing():
    house = _House(EVSessionLog())
    house.charge(datetime(2031, 6, 15, 12, tzinfo=timezone.utc), cycles=60, solar_w=9000.0)
    session = house.log.recent[0]
    assert session.energy_kwh > 0
    assert session.cost == pytest.approx(0.0)


def test_no_charger_tracks_nothing():
    log = EVSessionLog()
    house = _House(log)
    data = house.cycle(datetime(2031, 10, 15, 12, tzinfo=timezone.utc), None)
    assert data.ev_sessions is None
    assert log.is_empty


def test_no_log_leaves_the_snapshot_without_sessions():
    house = _House(None)
    data = house.cycle(
        datetime(2031, 10, 15, 12, tzinfo=timezone.utc), _charger(EVChargerState.CONNECTED, 0)
    )
    assert data.ev_sessions is None
