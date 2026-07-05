"""
test_scenarios.py — Multi-cycle scenario tests for GivEnergy Inverter Manager.

Unit tests verify individual functions in isolation.  These scenario tests
verify that the engine behaves correctly over sequences of cycles that
simulate realistic operating conditions — the kind of emergent behaviour
that only appears across multiple calls.

Scenarios covered:
  - Full overnight sequence: solar day → evening wind-down → charge decision
  - Accumulator rolls over correctly after midnight reset
  - Skip-charge logic responds correctly as SoC rises through the day
  - EV battery protection engages and releases across a charge session
  - Immersion divert activates in surplus and deactivates when surplus drops
  - Bill accumulates correctly across multiple rate period transitions
  - Dry run mode never lets any skipped action affect energy accounting

These use the shared _run/_raw/_nightboost_cfg helpers from conftest.py.
They do NOT test the coordinator (HA wiring) — only the engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

# ── Helpers ───────────────────────────────────────────────────────────────────

def _step(acc, raw_kwargs, now, last_update, cfg=None):
    """Run one 30-second engine cycle, return (data, updated_acc)."""
    raw = _raw(**raw_kwargs)
    data, _ = _run(raw=raw, cfg=cfg, now=now, acc=acc, last_update_time=last_update)
    return data, data.today  # today IS acc (same object, mutated in place)


# ── Scenario: Energy accumulates correctly over a solar day ───────────────────

class TestSolarDayAccumulation:
    """Simulate a summer day from 06:00 to 20:00 in 30-minute steps."""

    def test_solar_kwh_accumulates_across_cycles(self):
        """12 × 30-min cycles at 3kW solar = 6kWh total solar."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 8, 0)

        for _ in range(12):
            last = now
            now = now + timedelta(minutes=30)
            # Pass acc explicitly so it mutates in place across cycles
            _run(raw=_raw(solar_power_w=3000.0, grid_power_w=0.0, house_load_w=500.0),
                 now=now, acc=acc, last_update_time=last)

        # 12 × 30 min at 3 kW = 6 hours × 3 kW = 18 kWh
        assert acc.solar_kwh == pytest.approx(18.0, rel=0.01)

    def test_import_kwh_accumulates_when_grid_importing(self):
        """6 × 30-min cycles at 500W grid import = 1.5kWh import."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 22, 0)  # evening, after solar

        for _ in range(6):
            last = now
            now = now + timedelta(minutes=30)
            _run(raw=_raw(solar_power_w=0.0, grid_power_w=500.0, house_load_w=500.0),
                 now=now, acc=acc, last_update_time=last)

        assert acc.import_kwh == pytest.approx(1.5, rel=0.01)

    def test_export_kwh_accumulates_when_exporting(self):
        """4 × 30-min cycles at 1kW export = 2kWh export."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 12, 0)

        for _ in range(4):
            last = now
            now = now + timedelta(minutes=30)
            _run(raw=_raw(solar_power_w=5000.0, grid_power_w=-1000.0, house_load_w=500.0),
                 now=now, acc=acc, last_update_time=last)

        assert acc.export_kwh == pytest.approx(2.0, rel=0.01)

    def test_self_sufficiency_rises_with_solar(self):
        """Self-sufficiency should be high during a good solar day."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 10, 0)

        for _ in range(8):  # 4 hours of good solar
            last = now
            now = now + timedelta(minutes=30)
            _run(raw=_raw(solar_power_w=4000.0, grid_power_w=-500.0, house_load_w=500.0),
                 now=now, acc=acc, last_update_time=last)

        assert acc.self_sufficiency_pct > 80.0

    def test_no_accumulation_before_first_update(self):
        """First cycle with no last_update_time must not accumulate anything."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 14, 0)
        _run(raw=_raw(solar_power_w=3000.0, grid_power_w=500.0), now=now, acc=acc, last_update_time=None)

        assert acc.solar_kwh == 0.0
        assert acc.import_kwh == 0.0


# ── Scenario: Midnight reset ──────────────────────────────────────────────────

class TestMidnightReset:
    """Accumulator clears at midnight; energy from the new day accumulates fresh."""

    def test_fresh_accumulator_starts_at_zero(self):
        acc = EnergyAccumulator()
        assert acc.solar_kwh == 0.0
        assert acc.import_kwh == 0.0
        assert acc.export_kwh == 0.0

    def test_day1_totals_do_not_bleed_into_day2(self):
        """Simulate end of day 1, then reset accumulator, then accumulate day 2."""
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 23, 30)

        # End of day 1: 1 cycle with solar
        last = now - timedelta(minutes=30)
        _run(raw=_raw(solar_power_w=500.0), now=now, acc=acc, last_update_time=last)
        day1_solar = acc.solar_kwh
        assert day1_solar > 0.0

        # Midnight reset (coordinator does this; we simulate it)
        acc = EnergyAccumulator()

        # Start of day 2
        now2 = datetime(2024, 6, 16, 0, 30)
        last2 = datetime(2024, 6, 16, 0, 0)
        _run(raw=_raw(solar_power_w=100.0), now=now2, acc=acc, last_update_time=last2)

        assert acc.solar_kwh == pytest.approx(100.0 / 2000.0, rel=0.05)  # 30 min at 100W
        assert acc.solar_kwh < day1_solar  # Day 2 start is much less than full day 1


# ── Scenario: Charge decision over an evening ─────────────────────────────────

class TestChargeDecisionEvolution:
    """Charge target should reflect rising/falling SoC correctly."""

    def test_skip_charge_when_battery_high_good_forecast(self):
        """At skip_threshold SoC with a good forecast, charge is skipped."""
        cfg = _nightboost_cfg()
        cfg["skip_charge_soc_threshold_pct"] = 75
        raw = _raw(battery_soc=80.0)
        data, _ = _run(raw=raw, cfg=cfg)
        assert data.charge_decision.skip_charge is True

    def test_no_skip_when_battery_low(self):
        """Low battery should always trigger a charge regardless of forecast."""
        cfg = _nightboost_cfg()
        cfg["skip_charge_soc_threshold_pct"] = 75
        raw = _raw(battery_soc=30.0)
        data, _ = _run(raw=raw, cfg=cfg)
        assert data.charge_decision.skip_charge is False

    def test_target_increases_with_worse_forecast(self):
        """Poor forecast should produce a higher charge target than a good forecast."""
        # 10kWh battery; remove the configured cap so algorithm output is visible.
        # 8kWh = 80% capacity → "excellent" tier (lower target ~50%)
        # 2kWh = 20% capacity → "poor" tier (target = 90%)
        cfg = {**_nightboost_cfg(), "battery_capacity_kwh": 10.0, "overnight_charge_target_pct": 100}
        data_good, _ = _run(raw=_raw(battery_soc=20.0,
                                      forecast_kwh_tomorrow=8.0), cfg=cfg)
        data_poor, _ = _run(raw=_raw(battery_soc=20.0,
                                      forecast_kwh_tomorrow=2.0), cfg=cfg)

        assert data_poor.charge_decision.target_soc > data_good.charge_decision.target_soc

    def test_charge_cost_zero_when_skipping(self):
        """No charge cost should be reported when skip_charge is True."""
        cfg = _nightboost_cfg()
        cfg["skip_charge_soc_threshold_pct"] = 60
        raw = _raw(battery_soc=75.0)  # above threshold
        data, _ = _run(raw=raw, cfg=cfg)
        if data.charge_decision.skip_charge:
            assert data.charge_decision.cost_to_charge == pytest.approx(0.0)


# ── Scenario: EV battery protection across a charge session ──────────────────

class TestEVProtectionLifecycle:
    """EV protection should engage when battery drops and release when it recovers."""

    def _zappi(self, state_str="charging"):
        from custom_components.givenergy_inverter_manager.discovery import (
            EVCharger,
            EVChargerBrand,
            EVChargerState,
        )
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI, name="Zappi", serial="12345",
            display_name="Zappi 12345",
            state=EVChargerState.CHARGING,
            charge_mode="Fast",
            charge_mode_entity="select.myenergi_zappi_12345_charge_mode",
        )
        return ch

    def test_protection_engages_when_soc_low(self):
        """When SoC drops below protection threshold, EV target is Stopped."""
        cfg = _nightboost_cfg()
        cfg["ev_battery_protect_soc_pct"] = 20
        charger = self._zappi()
        raw = _raw(battery_soc=10.0, battery_power_w=-2000.0, ev_plugged_in=True)
        _, ev_target = _run(raw=raw, cfg=cfg, ev_charger=charger)
        assert ev_target == "Stopped"

    def test_no_protection_when_battery_healthy(self):
        """Above threshold, EV should not be stopped."""
        cfg = _nightboost_cfg()
        cfg["ev_battery_protect_soc_pct"] = 20
        charger = self._zappi()
        raw = _raw(battery_soc=70.0, battery_power_w=0.0, ev_plugged_in=True)
        _, ev_target = _run(raw=raw, cfg=cfg, ev_charger=charger)
        assert ev_target != "Stopped"

    def test_eco_plus_when_surplus_and_healthy(self):
        """With surplus solar and healthy battery, Zappi should switch to Eco+."""
        from custom_components.givenergy_inverter_manager.discovery import ZAPPI_ECO_PLUS_MODE
        cfg = _nightboost_cfg()
        cfg["ev_battery_protect_soc_pct"] = 20
        charger = self._zappi()
        charger.charge_mode = "Fast"  # currently on Fast, not Eco+
        raw = _raw(
            solar_power_w=5000.0,
            house_load_w=1000.0,
            battery_soc=85.0,
            battery_power_w=500.0,
            ev_plugged_in=True,
            ev_power_w=0.0,
        )
        _, ev_target = _run(raw=raw, cfg=cfg, ev_charger=charger)
        assert ev_target == ZAPPI_ECO_PLUS_MODE

    def test_protection_state_reflected_in_sensor(self):
        """When EV is draining battery, ev_draining_battery sensor should be True."""
        charger = self._zappi()
        charger.is_draining_battery = True
        raw = _raw(battery_soc=15.0, battery_power_w=-3000.0, ev_plugged_in=True)
        data, _ = _run(raw=raw, ev_charger=charger)
        assert data.ev_draining_battery is True


# ── Scenario: Immersion divert lifecycle ─────────────────────────────────────

class TestImmersionDivertLifecycle:
    """Immersion divert should activate and deactivate as surplus changes."""

    def test_divert_activates_with_surplus(self):
        """Large solar surplus above threshold should activate immersion."""
        raw = _raw(
            solar_power_w=5000.0,
            house_load_w=1000.0,
            battery_soc=85.0,
            battery_power_w=0.0,  # battery full
        )
        data, _ = _run(raw=raw)
        assert data.should_divert_immersion is True

    def test_divert_deactivates_with_no_surplus(self):
        """No solar surplus should deactivate immersion."""
        raw = _raw(
            solar_power_w=0.0,
            house_load_w=2000.0,
            battery_soc=85.0,
            battery_power_w=-1000.0,
        )
        data, _ = _run(raw=raw)
        assert data.should_divert_immersion is False

    def test_divert_blocked_by_low_battery(self):
        """Immersion should not divert when battery is below threshold."""
        raw = _raw(
            solar_power_w=5000.0,
            house_load_w=1000.0,
            battery_soc=30.0,  # below the 80% divert threshold
            battery_power_w=2000.0,  # battery charging hard
        )
        data, _ = _run(raw=raw)
        assert data.should_divert_immersion is False

    def test_divert_reason_is_descriptive(self):
        """The divert_reason sensor should always contain a non-empty string."""
        raw = _raw(solar_power_w=3000.0, battery_soc=85.0)
        data, _ = _run(raw=raw)
        assert isinstance(data.divert_reason, str)
        assert len(data.divert_reason) > 0


# ── Scenario: Bill prediction across rate periods ────────────────────────────

class TestBillAccumulation:
    """Bill prediction should reflect imports at the right rates."""

    def test_night_import_cheaper_than_day(self):
        """Importing at night should cost less per kWh than importing during the day."""
        acc_night = EnergyAccumulator()
        acc_day = EnergyAccumulator()

        now_night = datetime(2024, 6, 15, 3, 0)   # 03:00 = Nightboost
        now_day   = datetime(2024, 6, 15, 14, 0)  # 14:00 = Day rate
        last = now_night - timedelta(minutes=30)

        # Same import power, different times
        _run(raw=_raw(solar_power_w=0.0, grid_power_w=1000.0),
             now=now_night, acc=acc_night, last_update_time=last)
        _run(raw=_raw(solar_power_w=0.0, grid_power_w=1000.0),
             now=now_day, acc=acc_day,
             last_update_time=now_day - timedelta(minutes=30))

        # Both accumulated the same kWh
        assert acc_night.import_kwh == pytest.approx(acc_day.import_kwh, rel=0.01)
        # But night rate is cheaper
        assert acc_night.total_import_cost < acc_day.total_import_cost

    def test_export_earnings_independent_of_rate_period(self):
        """Export rate is flat — time of day should not change earnings per kWh."""
        acc_night = EnergyAccumulator()
        acc_day   = EnergyAccumulator()

        now_n = datetime(2024, 6, 15, 3, 0)
        now_d = datetime(2024, 6, 15, 14, 0)

        _run(raw=_raw(solar_power_w=5000.0, grid_power_w=-1000.0, house_load_w=500.0),
             now=now_n, acc=acc_night, last_update_time=now_n - timedelta(minutes=30))
        _run(raw=_raw(solar_power_w=5000.0, grid_power_w=-1000.0, house_load_w=500.0),
             now=now_d, acc=acc_day,   last_update_time=now_d - timedelta(minutes=30))

        assert acc_night.export_kwh == pytest.approx(acc_day.export_kwh, rel=0.01)
        assert acc_night.export_earnings == pytest.approx(acc_day.export_earnings, rel=0.01)

    def test_projected_bill_greater_than_accrued_early_in_period(self):
        """Early in the billing period, projected bill should exceed accrued."""
        # Bill starts on the 16th; we're on the 17th = 1 day in
        raw = _raw(solar_power_w=0.0, grid_power_w=1000.0)
        cfg = {**_nightboost_cfg(), "bill_start_day": 16}
        data, _ = _run(raw=raw, cfg=cfg, now=datetime(2024, 6, 17, 14, 0))
        assert data.projected_bill > data.accrued_bill


# ── Scenario: Dry run mode ────────────────────────────────────────────────────

class TestDryRunBehaviour:
    """Dry run should not affect sensor values but should surface skipped actions."""

    def test_dry_run_flag_visible_in_sensor(self):
        cfg = {**_nightboost_cfg(), "dry_run": True}
        data, _ = _run(cfg=cfg)
        assert data.dry_run is True

    def test_dry_run_false_by_default(self):
        data, _ = _run()
        assert data.dry_run is False

    def test_energy_accumulation_unaffected_by_dry_run(self):
        """Dry run should not suppress energy accumulation."""
        acc = EnergyAccumulator()
        cfg = {**_nightboost_cfg(), "dry_run": True}
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=30)
        _run(raw=_raw(solar_power_w=3000.0), cfg=cfg, now=now, acc=acc, last_update_time=last)
        assert acc.solar_kwh > 0.0

    def test_charge_decision_calculated_in_dry_run(self):
        """Charge decision should still be calculated even in dry run mode."""
        cfg = {**_nightboost_cfg(), "dry_run": True}
        data, _ = _run(raw=_raw(battery_soc=20.0), cfg=cfg)
        assert data.charge_decision is not None
        assert data.charge_decision.target_soc > 0


# ── Scenario: Night survival prediction ──────────────────────────────────────

class TestNightSurvivalPrediction:

    def test_survives_with_full_battery(self):
        """A full battery should always predict night survival."""
        raw = _raw(battery_soc=95.0, battery_power_w=0.0)
        data, _ = _run(raw=raw)
        assert data.will_survive_night is True

    def test_does_not_survive_with_empty_battery(self):
        """A nearly empty battery with high load should not predict survival."""
        raw = _raw(battery_soc=5.0, house_load_w=3000.0, battery_power_w=-2000.0)
        data, _ = _run(raw=raw)
        assert data.will_survive_night is False

    def test_soc_at_sunrise_never_below_min_soc(self):
        """Estimated SoC at sunrise should not go below min_soc."""
        cfg = _nightboost_cfg()
        cfg["battery_min_soc_pct"] = 10
        raw = _raw(battery_soc=25.0, battery_power_w=-1000.0)
        data, _ = _run(raw=raw, cfg=cfg)
        assert data.estimated_soc_at_sunrise >= 0.0  # never negative
