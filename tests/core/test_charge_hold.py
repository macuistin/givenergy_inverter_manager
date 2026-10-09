"""The published charge recommendation holds until the fresh target moves a clear step.

A step of 5 points is published once the held value has stood for an hour. A step of 15 points
is published at once. The write to the inverter is built from the fresh decision, so these
tests also pin that the fresh decision is never held.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
)
from custom_components.givenergy_inverter_manager.core.charge_hold import (
    HeldCharge,
    HoldReading,
    next_held_recommendation,
)
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

STEP = CHARGE_TARGET_HOLD_STEP_PCT
SMALL_HOURS = datetime(2024, 6, 15, 1, 30)


def _decision(
    target_soc: int = 87, *, skip: bool = False, reason: str = "r", soc: float = 40.0
) -> ChargeDecision:
    return ChargeDecision(
        target_soc=target_soc,
        skip_charge=skip,
        reason=reason,
        forecast_kwh=8.0,
        current_soc=soc,
        battery_capacity=19.0,
        car_plugged_in=False,
        cost_to_charge=1.0,
    )


def _changes(values: list) -> int:
    return sum(1 for before, after in zip(values, values[1:], strict=False) if before != after)


LARGE = CHARGE_TARGET_HOLD_LARGE_STEP_PCT
DWELL = timedelta(minutes=CHARGE_TARGET_HOLD_MIN_MINUTES)
PUBLISHED_AT = datetime(2024, 6, 15, 0, 0)
JUST_AFTER = HoldReading(PUBLISHED_AT + timedelta(minutes=1))
AFTER_DWELL = HoldReading(PUBLISHED_AT + DWELL)


def _held(decision: ChargeDecision) -> HeldCharge:
    return HeldCharge(decision, PUBLISHED_AT)


class TestNextHeldRecommendation:
    def test_the_first_decision_is_published_as_it_is(self):
        fresh = _decision(87)
        assert next_held_recommendation(HeldCharge(), fresh, JUST_AFTER) is fresh

    def test_a_target_inside_the_step_keeps_the_held_decision_and_its_reason(self):
        held = _decision(87, reason="held reason")
        fresh = _decision(87 + STEP - 1, reason="fresh reason")
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is held

    @pytest.mark.parametrize("direction", [1, -1])
    def test_a_step_is_published_once_the_held_value_has_stood_for_the_dwell(self, direction):
        held = _decision(87)
        fresh = _decision(87 + direction * STEP)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is fresh

    @pytest.mark.parametrize("direction", [1, -1])
    def test_a_step_inside_the_dwell_keeps_the_held_decision(self, direction):
        held = _decision(87)
        fresh = _decision(87 + direction * (LARGE - 1))
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is held

    def test_a_step_one_minute_short_of_the_dwell_keeps_the_held_decision(self):
        reading = HoldReading(PUBLISHED_AT + DWELL - timedelta(minutes=1))
        held = _decision(87)
        assert next_held_recommendation(_held(held), _decision(87 + STEP), reading) is held

    @pytest.mark.parametrize("direction", [1, -1])
    def test_a_large_step_is_published_at_once(self, direction):
        held = _decision(60)
        fresh = _decision(60 + direction * LARGE)
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is fresh

    def test_a_held_decision_with_no_publish_time_counts_as_stood_long_enough(self):
        held = _decision(87)
        fresh = _decision(87 + STEP)
        assert next_held_recommendation(HeldCharge(held), fresh, JUST_AFTER) is fresh

    def test_a_clock_that_runs_backwards_counts_as_stood_long_enough(self):
        reading = HoldReading(PUBLISHED_AT - timedelta(hours=1))
        held = _decision(87)
        fresh = _decision(87 + STEP)
        assert next_held_recommendation(_held(held), fresh, reading) is fresh

    def test_a_change_from_charging_to_skipping_is_published_at_once(self):
        held = _decision(87)
        fresh = _decision(88, skip=True)
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is fresh

    def test_a_change_from_skipping_to_charging_is_published_at_once(self):
        held = _decision(25, skip=True)
        fresh = _decision(60)
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is fresh


class TestAChangeOfKindThatChargesLittle:
    """Skipping and charging a few points are the same night, so the sensor keeps its value."""

    def test_skipping_to_a_charge_that_adds_under_a_step_is_held(self):
        held = _decision(80, skip=True, soc=88.0)
        fresh = _decision(88 + STEP - 1, soc=88.0)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is held

    def test_charging_to_a_skip_when_the_charge_adds_under_a_step_is_held(self):
        held = _decision(90, soc=86.0)
        fresh = _decision(80, skip=True, soc=88.0)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is held

    def test_a_charge_that_adds_a_step_is_published_once_the_value_has_stood(self):
        held = _decision(80, skip=True, soc=88.0)
        fresh = _decision(88 + STEP, soc=88.0)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is fresh

    def test_a_charge_that_adds_a_step_inside_the_hold_time_waits(self):
        held = _decision(80, skip=True, soc=88.0)
        fresh = _decision(88 + STEP, soc=88.0)
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is held

    def test_a_charge_that_adds_a_large_step_is_published_at_once(self):
        held = _decision(80, skip=True, soc=70.0)
        fresh = _decision(70 + LARGE, soc=70.0)
        assert next_held_recommendation(_held(held), fresh, JUST_AFTER) is fresh

    def test_a_charge_target_below_the_soc_adds_nothing(self):
        held = _decision(80, skip=True, soc=95.0)
        fresh = _decision(60, soc=95.0)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is held


class TestAChargeThatIsRunning:
    RUNNING = HoldReading(AFTER_DWELL.now, charge_running=True)

    def test_a_skip_is_not_published_while_the_charge_runs(self):
        held = _decision(90, soc=60.0)
        fresh = _decision(80, skip=True, soc=75.0)
        assert next_held_recommendation(_held(held), fresh, self.RUNNING) is held

    def test_a_skip_is_published_once_the_charge_has_stopped(self):
        held = _decision(90, soc=60.0)
        fresh = _decision(80, skip=True, soc=75.0)
        assert next_held_recommendation(_held(held), fresh, AFTER_DWELL) is fresh

    def test_a_skip_already_published_stays_while_the_charge_runs(self):
        held = _decision(80, skip=True, soc=88.0)
        fresh = _decision(80, skip=True, soc=89.0)
        assert next_held_recommendation(_held(held), fresh, self.RUNNING) is held

    def test_a_new_target_is_still_published_while_the_charge_runs(self):
        held = _decision(70, soc=60.0)
        fresh = _decision(70 + LARGE, soc=60.0)
        assert next_held_recommendation(_held(held), fresh, self.RUNNING) is fresh

    def test_a_charge_is_published_while_the_charge_runs_when_nothing_is_held(self):
        fresh = _decision(80, skip=True, soc=75.0)
        assert next_held_recommendation(HeldCharge(), fresh, self.RUNNING) is fresh


class TestSettle:
    def test_a_published_change_records_when_it_was_published(self):
        held = _held(_decision(60))
        fresh = _decision(60 + LARGE)
        held.settle(fresh, JUST_AFTER)
        assert held.decision is fresh
        assert held.published_at == JUST_AFTER.now

    def test_a_held_decision_keeps_its_publish_time(self):
        held = _held(_decision(60))
        kept = held.decision
        held.settle(_decision(61), JUST_AFTER)
        assert held.decision is kept
        assert held.published_at == PUBLISHED_AT

    def test_the_first_decision_is_stamped(self):
        held = HeldCharge()
        held.settle(_decision(60), JUST_AFTER)
        assert held.published_at == JUST_AFTER.now


def _jitter_series() -> list[float]:
    """House energy so far, swinging up then down in small uneven steps, as the early-morning
    extrapolation does."""
    climb = [1.40 + 0.0025 * i for i in range(41)]
    ramp = climb + climb[::-1][1:]
    noise = (0.004, -0.003, 0.0)
    return [round(kwh + noise[i % 3], 4) for i, kwh in enumerate(ramp)]


def _run_series(held: HeldCharge, house_kwh_series: list[float], **overrides):
    cfg = {**_nightboost_cfg(), "overnight_charge_target_pct": 100}
    cycles = []
    for house_kwh in house_kwh_series:
        acc = EnergyAccumulator()
        acc.house_kwh = house_kwh
        raw = _raw(battery_soc=40.0, battery_capacity_kwh=19.0, forecast_kwh_tomorrow=5.0)
        data, _ = _run(
            raw=raw,
            cfg=cfg,
            now=SMALL_HOURS,
            acc=acc,
            today_raw_forecast_kwh=8.0,
            held_charge=held,
            **overrides,
        )
        cycles.append(data)
    return cycles


class TestEngineHold:
    def test_the_jittering_series_really_jitters_without_the_hold(self):
        cycles = _run_series(HeldCharge(), _jitter_series())
        fresh_targets = [d.charge_decision.target_soc for d in cycles]
        assert _changes(fresh_targets) >= 20
        assert max(fresh_targets) - min(fresh_targets) >= STEP

    def test_the_published_target_changes_a_few_times_over_the_series(self):
        cycles = _run_series(HeldCharge(), _jitter_series())
        published = [d.published_charge_decision.target_soc for d in cycles]
        assert _changes(published) <= 3

    def test_the_published_reason_only_changes_when_the_published_target_does(self):
        cycles = _run_series(HeldCharge(), _jitter_series())
        reasons = [d.published_charge_decision.reason for d in cycles]
        targets = [d.published_charge_decision.target_soc for d in cycles]
        assert _changes(reasons) == _changes(targets)

    def test_the_fresh_decision_is_never_held(self):
        held = HeldCharge()
        cycles = _run_series(held, _jitter_series())
        fresh_targets = [d.charge_decision.target_soc for d in cycles]
        assert _changes(fresh_targets) >= 20
        last = cycles[-1]
        assert last.charge_decision.target_soc != last.published_charge_decision.target_soc

    def test_the_first_cycle_publishes_the_fresh_decision(self):
        data = _run_series(HeldCharge(), [1.45])[0]
        assert data.published_charge_decision == data.charge_decision

    def test_a_manual_target_override_is_published_at_once(self):
        held = HeldCharge()
        _run_series(held, [1.45])
        data = _run_series(held, [1.45], override_charge_target=91)[0]
        assert data.published_charge_decision.target_soc == 91
        assert data.published_charge_decision.reason == "Manual override: charge to 91%"
        assert data.charge_decision.target_soc == 91

    def test_a_manual_skip_override_is_published_at_once(self):
        held = HeldCharge()
        _run_series(held, [1.45])
        data = _run_series(held, [1.45], override_skip_charge=True)[0]
        assert data.published_charge_decision.skip_charge is True
        assert data.published_charge_decision.reason == "Manual override: skip overnight charge"

    def test_the_hold_is_not_moved_by_an_override(self):
        held = HeldCharge()
        before = _run_series(held, [1.45])[0].published_charge_decision
        _run_series(held, [1.45], override_charge_target=60)
        after = _run_series(held, [1.46])[0].published_charge_decision
        assert after == before

    def test_the_configured_maximum_caps_the_published_target(self):
        held = HeldCharge()
        cfg = {**_nightboost_cfg(), "overnight_charge_target_pct": 80}
        acc = EnergyAccumulator()
        acc.house_kwh = 1.45
        raw = _raw(battery_soc=40.0, battery_capacity_kwh=19.0, forecast_kwh_tomorrow=5.0)
        data, _ = _run(
            raw=raw, cfg=cfg, now=SMALL_HOURS, acc=acc, today_raw_forecast_kwh=8.0, held_charge=held
        )
        assert data.published_charge_decision.target_soc == 80
        assert "capped at configured max 80%" in data.published_charge_decision.reason

    def test_without_a_release_a_small_move_stays_held(self):
        held = HeldCharge()
        first = _run_series(held, [1.40])[0]
        later = _run_series(held, [1.43])[0]
        assert 0 < later.charge_decision.target_soc - first.charge_decision.target_soc < STEP
        assert later.published_charge_decision == first.published_charge_decision

    def test_releasing_the_hold_publishes_the_next_fresh_decision(self):
        held = HeldCharge()
        _run_series(held, [1.40])
        held.decision = None
        later = _run_series(held, [1.43])[0]
        assert later.published_charge_decision == later.charge_decision
