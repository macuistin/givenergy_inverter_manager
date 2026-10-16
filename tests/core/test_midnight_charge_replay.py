"""Replay of the night of 15 to 16 October, when the overnight charge target fell at midnight.

The recorded night showed a recommended target of 75 beside a reason that said "Target 91%", and a
fall from 100 to 75 at 00:00:24 with the forecast barely moving. These tests feed the engine
30 second cycles across midnight with the hold state carried over, and read the fresh decision
(what is written to the inverter) and the published one (what the sensors show).

The cause: from 00:00 to sunrise the plan charges for the solar day that is now today, and it read
the "tomorrow" sensor as the day after. That started the overmorrow reduction at midnight with no
day-after sensor set, though the evening plan, which has no day-after figure, applied none. The
plan now reads a day-after figure after midnight only when a day-after sensor is set. With one, the
evening and the small hours both read it, so the target does not step at midnight either.

The reason still leads with the simulation's own target ("Target 91%."). A reduction, the EV buffer
and the floors come after it, so with a day-after sensor the first number in the reason is not the
one written.

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
    CONF_FORECAST_ENTITY_D2,
)
from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CYCLE = timedelta(seconds=30)
MIDNIGHT = datetime(2026, 10, 16, 0, 0)
BEFORE_MIDNIGHT = datetime(2026, 10, 15, 23, 59, 30)
AFTER_MIDNIGHT = datetime(2026, 10, 16, 0, 0, 30)
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
    day_after_sensor: bool = False,
    forecast_17th_kwh: float = FORECAST_FOR_THE_17TH_KWH,
    average_daily_load_kwh: float = AVERAGE_DAILY_LOAD_KWH,
) -> list[Step]:
    """Cycles from start to end. The 17th's forecast is what the day-after sensor holds all night
    and what the tomorrow sensor holds from midnight.
    """
    held = HeldCharge()
    cfg = {**_nightboost_cfg(), "overnight_charge_target_pct": 100}
    if day_after_sensor:
        cfg[CONF_FORECAST_ENTITY_D2] = "sensor.forecast_day_after"
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
        raw.forecast_kwh_d2 = forecast_17th_kwh if day_after_sensor and not after_midnight else None
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


def _at(steps: list[Step], when: datetime) -> Step:
    return next(step for step in steps if step.now == when)


@pytest.fixture(scope="module")
def night_without_a_day_after_sensor() -> list[Step]:
    return _replay(datetime(2026, 10, 15, 23, 55), datetime(2026, 10, 16, 2, 0))


@pytest.fixture(scope="module")
def night_with_a_day_after_sensor() -> list[Step]:
    return _replay(
        datetime(2026, 10, 15, 23, 55), datetime(2026, 10, 16, 2, 0), day_after_sensor=True
    )


class TestWithoutADayAfterSensor:
    def test_no_step_takes_points_off_the_target_all_night(self, night_without_a_day_after_sensor):
        assert all("Overmorrow" not in step.reason for step in night_without_a_day_after_sensor)

    def test_the_target_does_not_step_at_midnight(self, night_without_a_day_after_sensor):
        before = _at(night_without_a_day_after_sensor, BEFORE_MIDNIGHT)
        after = _at(night_without_a_day_after_sensor, AFTER_MIDNIGHT)
        assert abs(before.written - after.written) <= 2

    def test_the_target_written_is_the_one_the_reason_leads_with(
        self, night_without_a_day_after_sensor
    ):
        after = _at(night_without_a_day_after_sensor, AFTER_MIDNIGHT)
        assert after.written == after.simulation_target

    def test_the_sensors_show_the_written_decision(self, night_without_a_day_after_sensor):
        after = _at(night_without_a_day_after_sensor, AFTER_MIDNIGHT)
        assert after.published == after.written
        assert after.published_reason == after.reason

    def test_a_tomorrow_forecast_above_the_battery_changes_nothing_either(self):
        steps = _replay(BEFORE_MIDNIGHT, AFTER_MIDNIGHT, forecast_17th_kwh=60.0)
        assert "Overmorrow" not in steps[-1].reason
        assert abs(steps[0].written - steps[-1].written) <= 2


class TestWithADayAfterSensor:
    def test_the_evening_and_the_small_hours_apply_the_same_reduction(
        self, night_with_a_day_after_sensor
    ):
        before = _at(night_with_a_day_after_sensor, BEFORE_MIDNIGHT)
        after = _at(night_with_a_day_after_sensor, AFTER_MIDNIGHT)
        assert f"reduced target by {OVERMORROW_REDUCTION_PCT}%" in before.reason
        assert f"reduced target by {OVERMORROW_REDUCTION_PCT}%" in after.reason

    def test_the_target_does_not_step_at_midnight(self, night_with_a_day_after_sensor):
        before = _at(night_with_a_day_after_sensor, BEFORE_MIDNIGHT)
        after = _at(night_with_a_day_after_sensor, AFTER_MIDNIGHT)
        assert abs(before.written - after.written) <= 2

    def test_the_reason_leads_with_a_target_that_is_not_the_written_one(
        self, night_with_a_day_after_sensor
    ):
        after = _at(night_with_a_day_after_sensor, AFTER_MIDNIGHT)
        assert after.reason.startswith("Forward simulation:")
        assert after.simulation_target > after.written

    def test_a_forecast_the_battery_can_absorb_has_no_reduction(self):
        steps = _replay(
            BEFORE_MIDNIGHT,
            AFTER_MIDNIGHT,
            day_after_sensor=True,
            forecast_17th_kwh=CAPACITY_KWH - 1,
        )
        assert all("Overmorrow" not in step.reason for step in steps)

    @pytest.mark.parametrize("load_kwh", [9.0, 11.0, 13.0, 15.0, 17.0])
    def test_the_written_target_is_the_simulation_less_the_reduction_never_under_the_floor(
        self, load_kwh
    ):
        after = _replay(
            AFTER_MIDNIGHT,
            AFTER_MIDNIGHT,
            day_after_sensor=True,
            average_daily_load_kwh=load_kwh,
        )[0]
        assert after.written == max(after.simulation_target - OVERMORROW_REDUCTION_PCT, FLOOR_PCT)
