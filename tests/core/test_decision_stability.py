"""The published charge decision is stable around midnight, sunrise and a running charge.

Each test replays the engine in 30 second cycles with the hold state carried over, as the
coordinator does, and counts what the sensors would have published. The fresh decision is
what the inverter write reads, so these tests also pin that it keeps moving.
"""

from datetime import datetime, timedelta

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
)
from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CYCLE = timedelta(seconds=30)
MIDNIGHT = datetime(2024, 6, 15, 0, 0)
CAPACITY_KWH = 19.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _changes(values: list) -> int:
    return sum(1 for before, after in zip(values, values[1:], strict=False) if before != after)


# ── The recommended target ────────────────────────────────────────────────────

DRIFT_FROM_MINUTE = 30  # the day's load total is trusted from here
DRIFT_MINUTES = 70
DRIFT_START_KWH = 20.0
DRIFT_END_KWH = 22.5


def _extrapolated_daily_kwh(minute: float) -> float:
    """The day's load as the extrapolation reads it: it climbs as the small hours go by."""
    progress = _clamp01((minute - DRIFT_FROM_MINUTE) / DRIFT_MINUTES)
    return DRIFT_START_KWH + (DRIFT_END_KWH - DRIFT_START_KWH) * progress


def _drift_cycle(now: datetime, held: HeldCharge):
    minute = (now - MIDNIGHT).total_seconds() / 60
    acc = EnergyAccumulator()
    acc.house_kwh = _extrapolated_daily_kwh(minute) * minute / 1440
    raw = _raw(battery_soc=40.0, battery_capacity_kwh=CAPACITY_KWH, forecast_kwh_tomorrow=5.0)
    data, _ = _run(
        raw=raw,
        cfg={**_nightboost_cfg(), "overnight_charge_target_pct": 100},
        now=now,
        acc=acc,
        today_raw_forecast_kwh=8.0,
        held_charge=held,
    )
    return data


def _drift_night() -> list:
    """00:30 to 03:00, the load estimate rising slowly with nothing else changing."""
    held = HeldCharge()
    start = MIDNIGHT + timedelta(minutes=DRIFT_FROM_MINUTE)
    steps = int(150 * 60 / CYCLE.total_seconds())
    return [_drift_cycle(start + CYCLE * i, held) for i in range(steps)]


class TestASlowDriftInTheLoadEstimate:
    def test_premise_the_fresh_target_drifts_by_several_steps(self):
        fresh = [d.charge_decision.target_soc for d in _drift_night()]
        assert max(fresh) - min(fresh) >= 2 * CHARGE_TARGET_HOLD_STEP_PCT

    def test_the_published_target_keeps_each_value_for_the_hold_time(self):
        cycles = _drift_night()
        published = [(d.published_charge_decision.target_soc) for d in cycles]
        published_at = [
            MIDNIGHT + timedelta(minutes=DRIFT_FROM_MINUTE) + CYCLE * i for i in range(len(cycles))
        ]
        last_change = published_at[0]
        for i in range(1, len(published)):
            if published[i] == published[i - 1]:
                continue
            large = abs(published[i] - published[i - 1]) >= CHARGE_TARGET_HOLD_LARGE_STEP_PCT
            stood = published_at[i] - last_change >= timedelta(
                minutes=CHARGE_TARGET_HOLD_MIN_MINUTES
            )
            assert large or stood, (
                f"{published_at[i]:%H:%M:%S} moved {published[i - 1]}->{published[i]}"
            )
            last_change = published_at[i]

    def test_the_fresh_target_is_never_held(self):
        cycles = _drift_night()
        fresh = [d.charge_decision.target_soc for d in cycles]
        published = [d.published_charge_decision.target_soc for d in cycles]
        assert _changes(fresh) > _changes(published) + 5
