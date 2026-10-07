"""The published charge recommendation holds until the fresh target moves a clear step.

The write to the inverter is built from the fresh decision, so these tests also pin that the
fresh decision is never held.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.const import CHARGE_TARGET_HOLD_STEP_PCT
from custom_components.givenergy_inverter_manager.core.charge_hold import (
    HeldCharge,
    next_held_recommendation,
)
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

STEP = CHARGE_TARGET_HOLD_STEP_PCT
SMALL_HOURS = datetime(2024, 6, 15, 1, 30)


def _decision(target_soc: int = 87, *, skip: bool = False, reason: str = "r") -> ChargeDecision:
    return ChargeDecision(
        target_soc=target_soc,
        skip_charge=skip,
        reason=reason,
        forecast_kwh=8.0,
        current_soc=40.0,
        battery_capacity=19.0,
        car_plugged_in=False,
        cost_to_charge=1.0,
    )


def _changes(values: list) -> int:
    return sum(1 for before, after in zip(values, values[1:], strict=False) if before != after)


class TestNextHeldRecommendation:
    def test_the_first_decision_is_published_as_it_is(self):
        fresh = _decision(87)
        assert next_held_recommendation(None, fresh) is fresh

    def test_a_target_inside_the_step_keeps_the_held_decision_and_its_reason(self):
        held = _decision(87, reason="held reason")
        fresh = _decision(87 + STEP - 1, reason="fresh reason")
        assert next_held_recommendation(held, fresh) is held

    @pytest.mark.parametrize("direction", [1, -1])
    def test_a_target_a_full_step_away_is_published(self, direction):
        held = _decision(87)
        fresh = _decision(87 + direction * STEP)
        assert next_held_recommendation(held, fresh) is fresh

    def test_a_change_from_charging_to_skipping_is_published_at_once(self):
        held = _decision(87)
        fresh = _decision(88, skip=True)
        assert next_held_recommendation(held, fresh) is fresh

    def test_a_change_from_skipping_to_charging_is_published_at_once(self):
        held = _decision(25, skip=True)
        fresh = _decision(26)
        assert next_held_recommendation(held, fresh) is fresh


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
