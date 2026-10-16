"""Replay of the night of 15 to 16 October, when the overnight charge target fell at midnight.

The recorded night showed a recommended target of 75 beside a reason that said "Target 91%", and a
fall from 100 to 75 at 00:00:24 with the forecast barely moving. These tests feed the engine
the same kind of cycles, 30 seconds apart across midnight with the hold state carried over, and
read the fresh decision (what is written to the inverter) and the published one (what the sensors
show).

They pin what the engine does today, so that the cause is on record before it is changed. They do
not say the behaviour is right. Whoever fixes the issue changes the tests that name the behaviour
they change.

What the replay shows:

- No day-after forecast is configured, so before midnight the plan has no overmorrow step.
- After 00:00 and before sunrise the engine charges for the solar day that is now today, and it
  hands the "tomorrow" forecast to the plan as the day after. The overmorrow reduction then applies,
  though nothing about the weather changed. The target falls by the reduction at the midnight
  rollover, and a step of 15 points or more is published at once.
- The reason starts with the simulation's own target ("Target 91%."). The reduction and the floors
  come after it, so the first number in the reason is not the one that is written.

Not covered: the plan text that flipped between 100 and 93 earlier in the evening. It does not
reproduce without that evening's load history.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_MIN_TARGET_HEADROOM_PCT,
    CHARGE_SHOULDER_MIN_SOC,
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
)
from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CYCLE = timedelta(seconds=30)
MIDNIGHT = datetime(2026, 10, 16, 0, 0)
CAPACITY_KWH = 19.0
SOC_PCT = 62.0
FORECAST_FOR_THE_16TH_KWH = 23.8
FORECAST_FOR_THE_17TH_KWH = 25.1
AVERAGE_DAILY_LOAD_KWH = 15.0
# int(((25.1 / 19.0 x 100) - 100) / 2): the points the overmorrow step takes off.
OVERMORROW_REDUCTION_PCT = 16
# October is a shoulder month, so the floor under the target is the raised minimum plus headroom.
FLOOR_PCT = CHARGE_SHOULDER_MIN_SOC + CHARGE_MIN_TARGET_HEADROOM_PCT


@dataclass(frozen=True)
class Step:
    now: datetime
    written: int
    published: int
    reason: str
    published_reason: str

    @property
    def simulation_target(self) -> int:
        """The target the reason leads with: the simulation's, before any later step."""
        found = re.search(r"Target (\d+)%\.", self.reason)
        assert found, self.reason
        return int(found.group(1))


def _replay(
    start: datetime,
    end: datetime,
    *,
    forecast_17th_kwh: float = FORECAST_FOR_THE_17TH_KWH,
    average_daily_load_kwh: float = AVERAGE_DAILY_LOAD_KWH,
) -> list[Step]:
    held = HeldCharge()
    cfg = {**_nightboost_cfg(), "overnight_charge_target_pct": 100}
    steps = []
    now = start
    while now <= end:
        after_midnight = now >= MIDNIGHT
        minute_of_day = (now - now.replace(hour=0, minute=0, second=0)).total_seconds() / 60
        raw = _raw(
            battery_soc=SOC_PCT,
            battery_capacity_kwh=CAPACITY_KWH,
            solar_power_w=0.0,
            forecast_kwh_tomorrow=(
                forecast_17th_kwh if after_midnight else FORECAST_FOR_THE_16TH_KWH
            ),
        )
        acc = EnergyAccumulator()
        acc.house_kwh = average_daily_load_kwh * minute_of_day / 1440
        data, _ = _run(
            raw=raw,
            cfg=cfg,
            now=now,
            acc=acc,
            today_raw_forecast_kwh=FORECAST_FOR_THE_16TH_KWH,
            held_charge=held,
        )
        fresh, published = data.charge_decision, data.published_charge_decision
        steps.append(
            Step(now, fresh.target_soc, published.target_soc, fresh.reason, published.reason)
        )
        now += CYCLE
    return steps


@pytest.fixture(scope="module")
def night() -> list[Step]:
    return _replay(datetime(2026, 10, 15, 23, 55), datetime(2026, 10, 16, 2, 0))


def _at(steps: list[Step], when: datetime) -> Step:
    return next(step for step in steps if step.now == when)


class TestTheNightReplay:
    def test_no_day_after_forecast_is_configured_so_the_evening_has_no_overmorrow_step(self, night):
        evening = [step for step in night if step.now < MIDNIGHT]
        assert all("Overmorrow" not in step.reason for step in evening)

    def test_the_written_target_falls_at_the_midnight_rollover(self, night):
        before = _at(night, datetime(2026, 10, 15, 23, 59, 30))
        after = _at(night, datetime(2026, 10, 16, 0, 0, 0))
        assert before.written - after.written >= 14

    def test_the_fall_is_the_overmorrow_reduction_not_a_change_in_the_simulation(self, night):
        before = _at(night, datetime(2026, 10, 15, 23, 59, 30))
        after = _at(night, datetime(2026, 10, 16, 0, 0, 0))
        assert abs(after.simulation_target - before.simulation_target) <= 1
        assert after.written == after.simulation_target - OVERMORROW_REDUCTION_PCT
        assert f"Overmorrow {FORECAST_FOR_THE_17TH_KWH:.1f}kWh" in after.reason
        assert f"reduced target by {OVERMORROW_REDUCTION_PCT}%" in after.reason

    def test_the_reason_leads_with_a_target_that_is_not_the_written_one(self, night):
        after = _at(night, datetime(2026, 10, 16, 0, 0, 30))
        assert after.reason.startswith("Forward simulation:")
        assert after.simulation_target > after.written + OVERMORROW_REDUCTION_PCT - 2

    def test_the_fall_is_published_at_once_because_it_is_a_large_step(self, night):
        before = _at(night, datetime(2026, 10, 15, 23, 59, 30))
        after = _at(night, datetime(2026, 10, 16, 0, 0, 30))
        assert before.published - after.written >= CHARGE_TARGET_HOLD_LARGE_STEP_PCT - 1
        assert after.published == after.written

    def test_the_night_stays_reduced_until_sunrise(self, night):
        small_hours = [step for step in night if step.now >= MIDNIGHT]
        assert all("Overmorrow" in step.reason for step in small_hours)

    def test_the_reason_the_sensors_show_follows_the_written_decision(self, night):
        after = _at(night, datetime(2026, 10, 16, 0, 0, 30))
        assert after.published_reason == after.reason


class TestWhatTheFallDependsOn:
    def test_an_unchanged_forecast_still_falls_at_midnight(self):
        steps = _replay(
            datetime(2026, 10, 15, 23, 59, 30),
            datetime(2026, 10, 16, 0, 0, 30),
            forecast_17th_kwh=FORECAST_FOR_THE_16TH_KWH,
        )
        before, after = steps[0], steps[-1]
        assert before.written - after.written >= 10
        assert "Overmorrow" in after.reason

    def test_a_forecast_the_battery_can_absorb_has_no_fall(self):
        steps = _replay(
            datetime(2026, 10, 15, 23, 59, 30),
            datetime(2026, 10, 16, 0, 0, 30),
            forecast_17th_kwh=CAPACITY_KWH - 1,
        )
        assert "Overmorrow" not in steps[-1].reason
        assert steps[0].written - steps[-1].written <= 2

    @pytest.mark.parametrize("load_kwh", [9.0, 11.0, 13.0, 15.0, 17.0])
    def test_the_written_target_is_the_simulation_less_the_reduction_never_under_the_floor(
        self, load_kwh
    ):
        after = _replay(
            datetime(2026, 10, 16, 0, 0, 24),
            datetime(2026, 10, 16, 0, 0, 24),
            average_daily_load_kwh=load_kwh,
        )[0]
        assert after.written == max(after.simulation_target - OVERMORROW_REDUCTION_PCT, FLOOR_PCT)
