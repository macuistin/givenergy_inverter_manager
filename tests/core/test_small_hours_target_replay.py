"""Replay of the small hours of 17 October, when the overnight target flapped between 100 and 75.

The target went 100 to 75 at 00:00:13 and then flipped back and forth six times by 01:11, each
time the house energy counter ticked up by 0.1 kWh (00:30:43, 01:02:44, 01:10:14). The forecast and
the SoC did not move. The cause was the average daily load: it fell back to a fixed 15 kWh at
midnight, then, from 00:30, extrapolated a few tenths of a kWh to 24 hours, so one tick of the
counter moved it by about 5 kWh a day and the target by 28 points.

The estimate now starts from yesterday's load and hands over to the extrapolation by 06:00. These
tests feed the engine 30 second cycles across midnight with a house counter that moves in 0.1 kWh
steps, as the real one does.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CYCLE = timedelta(seconds=30)
START = datetime(2026, 10, 16, 23, 50)
END = datetime(2026, 10, 17, 2, 0)
MIDNIGHT = datetime(2026, 10, 17, 0, 0)
HOUSE_KWH_PER_DAY = 22.0
COUNTER_STEP_KWH = 0.1
CAPACITY_KWH = 19.0
FORECAST_KWH = 24.5


@dataclass(frozen=True)
class Step:
    now: datetime
    written: int
    published: int


def _counter_kwh(now: datetime) -> float:
    """House energy so far today as a counter that moves in 0.1 kWh steps."""
    minutes = (now - now.replace(hour=0, minute=0, second=0)).total_seconds() / 60
    exact = HOUSE_KWH_PER_DAY * minutes / 1440
    return math.floor(exact / COUNTER_STEP_KWH) * COUNTER_STEP_KWH


def _replay(*, yesterday_kwh: float | None) -> list[Step]:
    held = HeldCharge()
    cfg = {**_nightboost_cfg(), "overnight_charge_target_pct": 100}
    yesterday = None
    if yesterday_kwh is not None:
        yesterday = EnergyAccumulator()
        yesterday.house_kwh = yesterday_kwh
    steps = []
    now = START
    while now <= END:
        raw = _raw(
            battery_soc=60.0,
            battery_capacity_kwh=CAPACITY_KWH,
            solar_power_w=0.0,
            forecast_kwh_tomorrow=FORECAST_KWH,
        )
        acc = EnergyAccumulator()
        acc.house_kwh = _counter_kwh(now)
        data, _ = _run(
            raw=raw,
            cfg=cfg,
            now=now,
            acc=acc,
            acc_yesterday=yesterday,
            today_raw_forecast_kwh=FORECAST_KWH,
            held_charge=held,
        )
        steps.append(
            Step(now, data.charge_decision.target_soc, data.published_charge_decision.target_soc)
        )
        now += CYCLE
    return steps


@pytest.fixture(scope="module")
def night() -> list[Step]:
    return _replay(yesterday_kwh=HOUSE_KWH_PER_DAY)


def _changes(values: list[int]) -> int:
    return sum(1 for before, after in zip(values, values[1:], strict=False) if before != after)


class TestWithYesterdaysLoad:
    def test_the_written_target_stays_within_a_few_points_all_night(self, night):
        written = [step.written for step in night]
        assert max(written) - min(written) <= 5

    def test_no_cycle_moves_the_written_target_by_a_large_step(self, night):
        written = [step.written for step in night]
        assert max(abs(b - a) for a, b in zip(written, written[1:], strict=False)) < 10

    def test_the_target_does_not_step_at_midnight(self, night):
        before = next(s for s in night if s.now == datetime(2026, 10, 16, 23, 59, 30))
        after = next(s for s in night if s.now == datetime(2026, 10, 17, 0, 0, 30))
        assert abs(before.written - after.written) <= 2

    def test_the_sensors_publish_few_changes_over_the_night(self, night):
        assert _changes([step.published for step in night]) <= 2


class TestWithoutYesterdaysLoad:
    """A first night has no yesterday. It keeps the old fixed fallback, and settles by 06:00."""

    def test_the_replay_runs_and_publishes_a_target(self):
        steps = _replay(yesterday_kwh=None)
        assert all(0 < step.published <= 100 for step in steps)
