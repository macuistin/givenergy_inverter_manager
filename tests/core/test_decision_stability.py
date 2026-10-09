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
    CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES,
    CHARGE_WINDOW_HOLD_STEP_MINUTES,
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


# ── Skipping and charging ─────────────────────────────────────────────────────

AUTUMN_NIGHT = datetime(2026, 10, 9, 0, 0)
HOUSE_LOAD_KW = 1.07
NOISE_FLOOR_W = 10.0
BELOW_FLOOR_W = 9.0
ABOVE_FLOOR_W = 12.0


def _autumn_cfg() -> dict:
    return {**_nightboost_cfg(), "overnight_charge_target_pct": 90}


def _autumn_cycle(now: datetime, held: HeldCharge, **raw_overrides):
    """One cycle on an autumn night, the house drawing a steady load since midnight."""
    minute = (now - AUTUMN_NIGHT).total_seconds() / 60
    acc = EnergyAccumulator()
    acc.house_kwh = HOUSE_LOAD_KW * minute / 60
    raw = _raw(
        battery_capacity_kwh=CAPACITY_KWH,
        house_load_w=HOUSE_LOAD_KW * 1000,
        forecast_kwh_tomorrow=21.7,
        **raw_overrides,
    )
    data, _ = _run(
        raw=raw,
        cfg=_autumn_cfg(),
        now=now,
        acc=acc,
        today_raw_forecast_kwh=22.0,
        held_charge=held,
    )
    return data


def _dawn_cycles() -> list:
    """08:00 to 08:10 with the solar reading flickering across the noise floor."""
    held = HeldCharge()
    start = AUTUMN_NIGHT + timedelta(hours=8)
    cycles = []
    for i in range(20):
        solar_w = BELOW_FLOOR_W if i % 2 == 0 else ABOVE_FLOOR_W
        cycles.append(
            _autumn_cycle(
                start + CYCLE * i,
                held,
                battery_soc=87.0,
                solar_power_w=solar_w,
                battery_power_w=0.0,
            )
        )
    return cycles


class TestSolarFlickeringAtDawn:
    def test_premise_the_fresh_plan_flips_with_each_reading(self):
        fresh = [d.charge_decision.skip_charge for d in _dawn_cycles()]
        assert _changes(fresh) >= 10

    def test_the_published_plan_does_not_flip(self):
        published = [d.published_charge_decision.skip_charge for d in _dawn_cycles()]
        assert _changes(published) == 0

    def test_the_published_reason_does_not_churn(self):
        reasons = [d.published_charge_decision.reason for d in _dawn_cycles()]
        assert _changes(reasons) == 0


def _charging_cycles() -> list:
    """02:00 to 04:00 on the cheap rate, the battery climbing through the skip threshold."""
    held = HeldCharge()
    start = AUTUMN_NIGHT + timedelta(hours=2)
    charge_pct_per_cycle = 3.3 / CAPACITY_KWH * 100 * CYCLE.total_seconds() / 3600
    cycles = []
    for i in range(240):
        cycles.append(
            _autumn_cycle(
                start + CYCLE * i,
                held,
                battery_soc=min(90.0, 50.0 + charge_pct_per_cycle * i),
                solar_power_w=0.0,
                battery_power_w=3300.0,
                grid_power_w=4300.0,
            )
        )
    return cycles


class TestACrossingOfTheSkipThresholdDuringTheCharge:
    def test_premise_the_fresh_plan_turns_to_skip_part_way_through(self):
        fresh = [d.charge_decision.skip_charge for d in _charging_cycles()]
        assert fresh[0] is False
        assert fresh[-1] is True

    def test_the_published_plan_never_says_skipping_while_the_charge_runs(self):
        published = [d.published_charge_decision.skip_charge for d in _charging_cycles()]
        assert not any(published)

    def test_the_fresh_plan_is_still_the_one_the_write_would_read(self):
        last = _charging_cycles()[-1]
        assert last.charge_decision.skip_charge is True
        assert last.published_charge_decision.skip_charge is False


# ── The window end ────────────────────────────────────────────────────────────

EVENING = datetime(2026, 10, 8, 21, 0)
CHARGE_RATE_W = 3300.0
START_SOC = 40.0
WINDOW_END_MINUTE_LIMIT = 8 * 60


def _evening_cycle(now: datetime, held: HeldCharge, charge_rate_w: float = CHARGE_RATE_W):
    """The battery runs down through the evening, so the plan needs a little longer each hour."""
    hours = (now - EVENING).total_seconds() / 3600
    soc = START_SOC - HOUSE_LOAD_KW * hours / CAPACITY_KWH * 100
    since_midnight_h = (now - now.replace(hour=0, minute=0, second=0)).total_seconds() / 3600
    acc = EnergyAccumulator()
    acc.house_kwh = HOUSE_LOAD_KW * since_midnight_h
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=0.0,
        house_load_w=HOUSE_LOAD_KW * 1000,
        battery_power_w=-HOUSE_LOAD_KW * 1000,
        battery_charge_rate_w=charge_rate_w,
        forecast_kwh_tomorrow=2.0,
    )
    data, _ = _run(
        raw=raw,
        cfg=_autumn_cfg(),
        now=now,
        acc=acc,
        today_raw_forecast_kwh=2.0,
        held_charge=held,
    )
    return data


def _evening_cycles() -> list:
    held = HeldCharge()
    steps = int(5 * 3600 / CYCLE.total_seconds())
    return [_evening_cycle(EVENING + CYCLE * i, held) for i in range(steps)]


def _end_minutes(windows: list) -> list[int]:
    return [w.end.hour * 60 + w.end.minute for w in windows]


class TestTheWindowThroughTheEvening:
    def test_premise_the_planned_end_creeps_on_in_small_steps(self):
        ends = _end_minutes([d.charge_window for d in _evening_cycles()])
        assert _changes(ends) >= 10
        assert max(ends) - min(ends) >= 2 * CHARGE_WINDOW_HOLD_STEP_MINUTES

    def test_the_published_end_moves_a_few_times(self):
        ends = _end_minutes([d.published_charge_window for d in _evening_cycles()])
        assert _changes(ends) <= 5

    def test_each_published_move_is_a_clear_step(self):
        ends = _end_minutes([d.published_charge_window for d in _evening_cycles()])
        moves = [abs(b - a) for a, b in zip(ends, ends[1:], strict=False) if a != b]
        assert moves
        assert min(moves) >= CHARGE_WINDOW_HOLD_STEP_MINUTES

    def test_the_planned_window_is_never_held(self):
        cycles = _evening_cycles()
        planned = _end_minutes([d.charge_window for d in cycles])
        published = _end_minutes([d.published_charge_window for d in cycles])
        assert _changes(planned) > _changes(published) + 5
        assert planned[-1] != published[-1]

    def test_a_much_slower_charge_rate_is_published_at_once(self):
        held = HeldCharge()
        now = EVENING + timedelta(hours=1)
        before = _evening_cycle(now, held).published_charge_window
        after = _evening_cycle(now + CYCLE, held, charge_rate_w=CHARGE_RATE_W / 2)
        moved = _end_minutes([after.published_charge_window])[0] - _end_minutes([before])[0]
        assert moved >= CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES
        assert after.published_charge_window == after.charge_window

    def test_a_released_hold_publishes_the_next_planned_window(self):
        held = HeldCharge()
        _evening_cycles_with(held)
        held.release()
        data = _evening_cycle(EVENING + timedelta(hours=5, minutes=1), held)
        assert data.published_charge_window == data.charge_window


def _evening_cycles_with(held: HeldCharge) -> None:
    for i in range(int(5 * 3600 / CYCLE.total_seconds())):
        _evening_cycle(EVENING + CYCLE * i, held)


class TestTheWindowDuringTheCharge:
    def test_the_published_window_holds_still_while_the_charge_runs(self):
        held = HeldCharge()
        start = AUTUMN_NIGHT + timedelta(hours=2)
        windows = []
        for i in range(120):
            soc = 40.0 + 3.3 / CAPACITY_KWH * 100 * (i * CYCLE.total_seconds() / 3600)
            data = _autumn_cycle(
                start + CYCLE * i,
                held,
                battery_soc=soc,
                solar_power_w=0.0,
                battery_power_w=3300.0,
                grid_power_w=4300.0,
                battery_charge_rate_w=CHARGE_RATE_W,
            )
            windows.append(data.published_charge_window)
        assert len({w.end for w in windows}) == 1
