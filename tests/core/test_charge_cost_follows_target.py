"""The overnight charge cost is priced at the target that will be written.

The configured maximum, a manual fixed target and a manual skip change the decision's target
after the plan has priced it. These tests drive the engine and check that the cost on both the
fresh decision (what the inverter write reads) and the published one (what the Estimated
Overnight Charge Cost sensor reads) follows the target each one ends with, counts only the
energy above the SoC the decision was made at, and is zero on a skipped night.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import CHARGE_WINTER_SKIP_SOC_PCT
from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from tests.conftest import _nightboost_cfg, _raw, _run

CAPACITY_KWH = 19.0
WINTER_NIGHT = datetime(2031, 1, 15, 23, 0)
SUMMER_NIGHT = datetime(2031, 6, 15, 23, 0)
CAP_PCT = 80


def _cfg(cap_pct: int = CAP_PCT) -> dict:
    return {**_nightboost_cfg(), "overnight_charge_target_pct": cap_pct}


CHEAPEST_RATE = build_tariff(_cfg()).get_cheapest_rate().rate


def _expected_cost(current_soc: float, target_soc: int) -> float:
    """The energy from the SoC up to the target at the cheapest rate, as the plan prices it."""
    return max(0.0, CAPACITY_KWH * (target_soc - current_soc) / 100) * CHEAPEST_RATE


def _cycle(now: datetime, soc: float, **kwargs):
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=0.0,
        forecast_kwh_tomorrow=kwargs.pop("forecast_kwh", 4.0),
    )
    data, _ = _run(raw=raw, cfg=kwargs.pop("cfg", _cfg()), now=now, **kwargs)
    return data


def _both(data) -> tuple[ChargeDecision, ChargeDecision]:
    return data.charge_decision, data.published_charge_decision


class TestTheConfiguredMaximum:
    def test_a_capped_winter_plan_costs_the_capped_target(self):
        data = _cycle(WINTER_NIGHT, soc=40.0)
        for decision in _both(data):
            assert decision.target_soc == CAP_PCT
            assert "capped at configured max" in decision.reason
            assert decision.cost_to_charge == pytest.approx(_expected_cost(40.0, CAP_PCT))

    def test_the_cap_lowers_the_cost_below_the_uncapped_plan(self):
        uncapped = _cycle(WINTER_NIGHT, soc=40.0, cfg=_cfg(cap_pct=100))
        capped = _cycle(WINTER_NIGHT, soc=40.0)
        assert uncapped.charge_decision.target_soc == 100
        assert uncapped.charge_decision.cost_to_charge == pytest.approx(_expected_cost(40.0, 100))
        assert capped.charge_decision.cost_to_charge < uncapped.charge_decision.cost_to_charge

    def test_a_cap_at_or_below_the_soc_costs_nothing(self):
        data = _cycle(WINTER_NIGHT, soc=85.0)
        for decision in _both(data):
            assert decision.target_soc == CAP_PCT
            assert decision.cost_to_charge == 0.0


class TestAManualFixedTarget:
    SOC = 12.0

    def _night(self, **kwargs):
        """No solar tomorrow, so the plan charges well above the SoC."""
        return _cycle(SUMMER_NIGHT, soc=self.SOC, forecast_kwh=0.0, **kwargs)

    def _automatic_target(self) -> int:
        return self._night().charge_decision.target_soc

    def test_premise_the_automatic_target_leaves_room_both_ways(self):
        automatic = self._automatic_target()
        assert self.SOC + 10 < automatic < 90

    def test_a_fixed_target_above_the_automatic_one_costs_the_fixed_target(self):
        fixed = self._automatic_target() + 10
        data = self._night(override_charge_target=fixed)
        for decision in _both(data):
            assert decision.target_soc == fixed
            assert decision.cost_to_charge == pytest.approx(_expected_cost(self.SOC, fixed))

    def test_a_fixed_target_below_the_automatic_one_costs_the_fixed_target(self):
        fixed = self._automatic_target() - 10
        data = self._night(override_charge_target=fixed)
        for decision in _both(data):
            assert decision.target_soc == fixed
            assert decision.cost_to_charge == pytest.approx(_expected_cost(self.SOC, fixed))

    def test_a_fixed_target_above_the_cap_is_written_and_costed_uncapped(self):
        fixed = 95
        data = self._night(override_charge_target=fixed)
        for decision in _both(data):
            assert decision.target_soc == fixed
            assert decision.cost_to_charge == pytest.approx(_expected_cost(self.SOC, fixed))

    def test_a_fixed_target_below_the_soc_costs_nothing(self):
        data = self._night(override_charge_target=10)
        for decision in _both(data):
            assert decision.target_soc == 10
            assert decision.cost_to_charge == 0.0


class TestASkippedNight:
    def test_a_manual_skip_costs_nothing(self):
        data = _cycle(WINTER_NIGHT, soc=40.0, override_skip_charge=True)
        for decision in _both(data):
            assert decision.skip_charge
            assert decision.cost_to_charge == 0.0

    def test_an_automatic_winter_skip_costs_nothing(self):
        soc = float(CHARGE_WINTER_SKIP_SOC_PCT + 2)
        data = _cycle(WINTER_NIGHT, soc=soc, cfg=_cfg(cap_pct=100))
        for decision in _both(data):
            assert decision.skip_charge
            assert decision.target_soc == 100
            assert decision.cost_to_charge == 0.0

    def test_an_automatic_sunny_skip_costs_nothing(self):
        data = _cycle(SUMMER_NIGHT, soc=90.0, forecast_kwh=40.0)
        for decision in _both(data):
            assert decision.skip_charge
            assert decision.cost_to_charge == 0.0


class TestTheHeldAndFreshDecisions:
    """The published decision is held from an earlier cycle and keeps that cycle's SoC."""

    def _two_cycles(self, **kwargs):
        held = HeldCharge()
        _cycle(WINTER_NIGHT, soc=40.0, held_charge=held, **kwargs)
        later = WINTER_NIGHT + timedelta(minutes=10)
        return _cycle(later, soc=44.0, held_charge=held, **kwargs)

    def test_premise_the_published_decision_is_the_held_one(self):
        fresh, published = _both(self._two_cycles())
        assert published.current_soc == 40.0
        assert fresh.current_soc == 44.0

    def test_each_capped_decision_costs_its_own_target_from_its_own_soc(self):
        fresh, published = _both(self._two_cycles())
        assert fresh.target_soc == published.target_soc == CAP_PCT
        assert fresh.cost_to_charge == pytest.approx(_expected_cost(44.0, CAP_PCT))
        assert published.cost_to_charge == pytest.approx(_expected_cost(40.0, CAP_PCT))

    def test_each_fixed_target_decision_costs_the_fixed_target(self):
        fresh, published = _both(self._two_cycles(override_charge_target=60))
        assert fresh.cost_to_charge == pytest.approx(_expected_cost(44.0, 60))
        assert published.cost_to_charge == pytest.approx(_expected_cost(40.0, 60))

    def test_both_decisions_cost_nothing_on_a_manual_skip(self):
        fresh, published = _both(self._two_cycles(override_skip_charge=True))
        assert fresh.cost_to_charge == published.cost_to_charge == 0.0
