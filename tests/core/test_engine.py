"""
test_engine.py — Unit tests for engine.py (the pure logic layer).

These tests exercise build_coordinator_data() directly with plain Python inputs,
no Home Assistant required. This is the key benefit of the engine/proxy split:
the entire decision-making brain is testable without any HA setup.

Coverage targets:
  - build_tariff(): malformed periods, fallback, options override
  - accumulate_energy(): import/export/solar/ev/immersion, EV cost fraction
  - estimate_avg_daily_kwh(): early morning fallback, normal extrapolation
  - update_battery_stats(): cycle increment, full-charge detection
  - build_coordinator_data(): end-to-end snapshot correctness, overrides,
    clipping, immersion divert, bill prediction, EV action, night survival
"""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    CoordinatorData,
    accumulate_energy,
    build_coordinator_data,
    build_tariff,
    estimate_avg_daily_kwh,
    update_battery_stats,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.discovery import (
    ZAPPI_ECO_PLUS_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from tests.conftest import _nightboost_cfg, _raw, _run

# ── Fixtures ──────────────────────────────────────────────────────────────────


class TestBuildTariff:
    def test_builds_from_valid_cfg(self):
        tariff = build_tariff(_nightboost_cfg())
        assert len(tariff.rate_periods) == 2  # Night + Nightboost; Day is base_rate scalar
        assert tariff.base_rate == pytest.approx(0.3334)
        assert tariff.export_rate == pytest.approx(0.195)
        assert tariff.vat_rate == pytest.approx(9.0)

    def test_no_timed_periods_valid(self):
        """Empty rate_periods is valid; base_rate is the catch-all."""
        cfg = _nightboost_cfg()
        cfg["rate_periods"] = []
        tariff = build_tariff(cfg)
        assert len(tariff.rate_periods) == 0
        # get_current_rate should still work (returns base rate)
        from datetime import datetime

        r = tariff.get_current_rate(datetime(2024, 6, 15, 12, 0))
        assert r.name == "Day"

    def test_skips_malformed_period(self):
        cfg = _nightboost_cfg()
        cfg["rate_periods"] = [
            {"name": "Good", "rate": 0.30, "start": "08:00", "end": "23:00"},
            {"name": "Bad", "rate": "notanumber", "start": "23:00", "end": "08:00"},
        ]
        tariff = build_tariff(cfg)
        assert len(tariff.rate_periods) == 1
        assert tariff.rate_periods[0].name == "Good"

    def test_options_override_data(self):
        """Rate from options should win over rate in data."""
        cfg = _nightboost_cfg()
        cfg["export_rate"] = 0.21  # options value
        tariff = build_tariff(cfg)
        assert tariff.export_rate == pytest.approx(0.21)

    def test_defaults_used_when_keys_absent(self):
        tariff = build_tariff({})
        assert tariff.export_rate > 0
        assert len(tariff.rate_periods) >= 1


# ── accumulate_energy ─────────────────────────────────────────────────────────


class TestAccumulateEnergy:
    def _acc_after(self, raw_kwargs, elapsed_minutes=30):
        """Run one accumulation step and return the accumulator."""
        raw = _raw(**raw_kwargs)
        acc = EnergyAccumulator()
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=elapsed_minutes)
        accumulate_energy(acc, raw, tariff, "Day", now, last)
        return acc

    def test_no_accumulation_on_first_call(self):
        """No energy accumulated when last_update_time is None."""
        raw = _raw()
        acc = EnergyAccumulator()
        tariff = build_tariff(_nightboost_cfg())
        accumulate_energy(acc, raw, tariff, "Day", datetime.now(timezone.utc), None)
        assert acc.import_kwh == 0.0
        assert acc.solar_kwh == 0.0

    def test_import_accumulates_with_cost(self):
        acc = self._acc_after({"grid_power_w": 1000.0, "solar_power_w": 0.0})
        assert acc.import_kwh > 0
        assert acc.import_cost_by_period.get("Day", 0.0) > 0

    def test_export_accumulates_with_earnings(self):
        acc = self._acc_after({"grid_power_w": -2000.0, "solar_power_w": 3000.0})
        assert acc.export_kwh > 0
        assert acc.export_earnings > 0

    def test_solar_accumulated(self):
        acc = self._acc_after({"solar_power_w": 4000.0})
        assert acc.solar_kwh > 0

    def test_immersion_accumulated_when_on(self):
        acc = self._acc_after({"immersion_on": True, "immersion_wattage_w": 3000.0})
        assert acc.immersion_kwh > 0

    def test_immersion_not_accumulated_when_off(self):
        acc = self._acc_after({"immersion_on": False})
        assert acc.immersion_kwh == 0.0

    def test_ev_cost_fraction(self):
        """When EV and grid both drawing, EV cost is proportional fraction."""
        acc = self._acc_after(
            {
                "ev_power_w": 3000.0,
                "grid_power_w": 4000.0,  # 75% of import going to car
            }
        )
        assert acc.zappi_kwh > 0
        assert acc.zappi_cost > 0

    def test_no_ev_cost_when_no_grid_import(self):
        """EV charging from solar only — no grid cost attributed."""
        acc = self._acc_after(
            {
                "ev_power_w": 3000.0,
                "grid_power_w": 0.0,  # no grid import
                "solar_power_w": 5000.0,
            }
        )
        assert acc.zappi_kwh > 0
        assert acc.zappi_cost == 0.0  # no grid fraction

    def test_elapsed_time_scales_energy(self):
        """Longer elapsed time produces more accumulated energy."""
        acc_30 = self._acc_after({"solar_power_w": 2000.0}, elapsed_minutes=30)
        acc_60 = self._acc_after({"solar_power_w": 2000.0}, elapsed_minutes=60)
        assert acc_60.solar_kwh == pytest.approx(acc_30.solar_kwh * 2, rel=0.01)


# ── estimate_avg_daily_kwh ────────────────────────────────────────────────────


class TestEstimateAvgDailyKwh:
    def test_uses_fallback_early_morning(self):
        """Before min_minutes have elapsed, return fallback."""
        result = estimate_avg_daily_kwh(
            house_kwh_today=0.5,
            now=datetime(2024, 6, 15, 0, 15),  # only 15 min elapsed
            fallback_kwh=15.0,
            min_minutes=30,
        )
        assert result == pytest.approx(15.0)

    def test_extrapolates_from_partial_day(self):
        """At noon with 6kWh, should extrapolate to ~12kWh/day."""
        result = estimate_avg_daily_kwh(
            house_kwh_today=6.0,
            now=datetime(2024, 6, 15, 12, 0),  # 720 min elapsed
        )
        assert result == pytest.approx(12.0, rel=0.01)

    def test_never_below_absolute_min(self):
        """Always returns at least absolute_min."""
        result = estimate_avg_daily_kwh(
            house_kwh_today=0.0,
            now=datetime(2024, 6, 15, 23, 0),
            absolute_min=5.0,
        )
        assert result >= 5.0

    def test_normal_afternoon(self):
        """At 15:00 with 10kWh consumed, extrapolate to ~16kWh."""
        result = estimate_avg_daily_kwh(
            house_kwh_today=10.0,
            now=datetime(2024, 6, 15, 15, 0),  # 900 min = 62.5% of day
        )
        assert result == pytest.approx(10.0 * 1440 / 900, rel=0.01)


# ── update_battery_stats ──────────────────────────────────────────────────────


class TestUpdateBatteryStats:
    def test_no_change_on_first_call(self):
        """No cycle increment when last_soc is None (first update)."""
        stats = BatteryStats()
        update_battery_stats(stats, 80.0, None)
        assert stats.total_cycles == 0.0

    def test_cycle_increments_on_discharge(self):
        stats = BatteryStats()
        update_battery_stats(stats, 50.0, 80.0)
        assert stats.total_cycles == pytest.approx(0.30)

    def test_full_charge_date_set_at_99_pct(self):
        from datetime import date

        stats = BatteryStats()
        update_battery_stats(stats, 99.5, 90.0)
        assert stats.last_full_charge_date == date.today()

    def test_full_charge_date_not_set_below_99(self):
        stats = BatteryStats()
        update_battery_stats(stats, 98.9, 90.0)
        assert stats.last_full_charge_date is None

    def test_no_increment_when_soc_unchanged(self):
        stats = BatteryStats(total_cycles=5.0)
        update_battery_stats(stats, 70.0, 70.0)
        assert stats.total_cycles == pytest.approx(5.0)


# ── build_coordinator_data (end-to-end) ───────────────────────────────────────


class TestBuildCoordinatorData:
    def test_returns_coordinator_data(self):
        data, _ = _run()
        assert isinstance(data, CoordinatorData)

    def test_currency_symbol_resolved(self):
        cfg = _nightboost_cfg()
        cfg["currency"] = "GBP"
        data, _ = _run(cfg=cfg)
        assert data.currency_symbol == "£"

    def test_unknown_currency_falls_back_to_euro(self):
        cfg = _nightboost_cfg()
        cfg["currency"] = "XYZ"
        data, _ = _run(cfg=cfg)
        assert data.currency_symbol == "€"

    def test_raw_values_copied_to_snapshot(self):
        raw = _raw(solar_power_w=4500.0, battery_soc=65.0)
        data, _ = _run(raw=raw)
        assert data.solar_power_w == pytest.approx(4500.0)
        assert data.battery_soc == pytest.approx(65.0)

    def test_clipping_detected_at_95_pct(self):
        raw = _raw(solar_power_w=4800.0, inverter_max_w=5000.0)  # 96%
        data, _ = _run(raw=raw)
        assert data.is_clipping is True

    def test_no_clipping_below_threshold(self):
        raw = _raw(solar_power_w=4000.0, inverter_max_w=5000.0)  # 80%
        data, _ = _run(raw=raw)
        assert data.is_clipping is False

    def test_immersion_load_zero_when_off(self):
        raw = _raw(immersion_on=False)
        data, _ = _run(raw=raw)
        assert data.immersion_load_w == 0.0

    def test_immersion_load_set_when_on(self):
        raw = _raw(
            immersion_on=True,
        )
        data, _ = _run(raw=raw)
        assert data.immersion_load_w == pytest.approx(3000.0)

    def test_rest_of_house_derived_correctly(self):
        raw = _raw(
            house_load_w=5000.0,
            ev_power_w=2000.0,
            immersion_on=True,
        )
        # rest = 5000 - 2000 - 3000 = 0
        data, _ = _run(raw=raw)
        assert data.rest_of_house_w == pytest.approx(0.0)

    def test_rest_of_house_never_negative(self):
        raw = _raw(house_load_w=100.0, ev_power_w=2000.0)
        data, _ = _run(raw=raw)
        assert data.rest_of_house_w >= 0.0

    def test_charge_decision_present(self):
        data, _ = _run()
        assert data.charge_decision is not None
        assert data.charge_decision.target_soc > 0

    def test_override_charge_target_applied(self):
        data, _ = _run(override_charge_target=95)
        assert data.charge_decision.target_soc == 95
        assert data.charge_decision.skip_charge is False
        assert "Manual override" in data.charge_decision.reason

    def test_override_immersion_on(self):
        data, _ = _run(override_immersion=True)
        assert data.should_divert_immersion is True
        assert "Manual override" in data.divert_reason

    def test_override_immersion_off(self):
        data, _ = _run(override_immersion=False)
        assert data.should_divert_immersion is False

    def test_immersion_auto_diverts_with_surplus(self):
        """Auto divert: battery high + solar surplus → immersion on."""
        raw = _raw(
            solar_power_w=4500.0,
            house_load_w=500.0,
            battery_soc=85.0,
            battery_power_w=200.0,
            immersion_temp=40.0,
        )
        data, _ = _run(raw=raw)
        assert data.should_divert_immersion is True

    def test_bill_prediction_positive(self):
        """Accrued and projected bill are non-negative."""
        acc = EnergyAccumulator()
        acc.import_cost_by_period["Day"] = 5.0
        data, _ = _run(
            acc=acc,
            now=datetime(2024, 5, 20, 14, 0),  # 4 days into billing period
        )
        assert data.accrued_bill > 0
        assert data.projected_bill > 0
        assert data.days_in_period == 4
        assert data.days_remaining > 0

    def test_night_survival_positive_case(self):
        """Full battery at day time should survive the night."""
        raw = _raw(battery_soc=90.0)
        data, _ = _run(raw=raw, now=datetime(2024, 6, 15, 18, 0))
        assert data.will_survive_night is True
        assert data.estimated_soc_at_sunrise > 10.0

    def test_night_survival_negative_case(self):
        """Very low battery late at night may not survive."""
        raw = _raw(battery_soc=11.0)
        data, _ = _run(raw=raw, now=datetime(2024, 6, 15, 23, 0))
        # At 11% SoC with min 10%, only 1.9kWh usable over ~9 hours
        # With avg 15kWh/day = 0.625kWh/hour → likely runs out
        assert data.survival_reason != ""

    def test_ev_not_available_when_no_charger(self):
        data, _ = _run(ev_charger=None)
        assert data.ev_available is False

    def test_ev_available_when_charger_present(self):
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="123",
            display_name="Zappi (123)",
            state=EVChargerState.CONNECTED,
            charge_mode="Eco+",
        )
        data, _ = _run(ev_charger=ch)
        assert data.ev_available is True
        assert data.ev_charger_brand == EVChargerBrand.ZAPPI.value

    def test_ev_eco_plus_when_battery_ok_and_surplus(self):
        """When battery high and solar surplus available, engine requests Eco+."""
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="123",
            display_name="Zappi (123)",
            state=EVChargerState.CONNECTED,
            charge_mode="Stopped",
            charge_mode_entity="select.zappi_123_charge_mode",
        )
        raw = _raw(
            battery_soc=85.0,
            solar_power_w=4000.0,
            house_load_w=500.0,
            battery_power_w=200.0,
        )
        _, ev_target = _run(raw=raw, ev_charger=ch)
        assert ev_target == ZAPPI_ECO_PLUS_MODE

    def test_ev_no_action_when_disconnected(self):
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="123",
            display_name="Zappi (123)",
            state=EVChargerState.DISCONNECTED,
            charge_mode="Eco+",
        )
        _, ev_target = _run(ev_charger=ch)
        assert ev_target is None

    def test_rate_name_populated(self):
        """Current rate name should be set from tariff."""
        data, _ = _run(now=datetime(2024, 6, 15, 3, 0))  # 3am = Nightboost
        assert data.current_rate_name == "Nightboost"
        assert data.current_rate == pytest.approx(0.0965)

    def test_no_ev_target_for_non_zappi(self):
        """Non-Zappi chargers don't get mode-switched."""
        ch = EVCharger(
            brand=EVChargerBrand.WALLBOX,
            name="wb",
            serial="x",
            display_name="wb",
            state=EVChargerState.CHARGING,
        )
        ch.is_draining_battery = True
        raw = _raw(battery_soc=5.0, battery_power_w=-2000.0)
        _, ev_target = _run(raw=raw, ev_charger=ch)
        assert ev_target is None  # Wallbox has no mode_entity

    def test_energy_accumulation_happens(self):
        """When last_update_time is set, energy should be accumulated."""
        raw = _raw(solar_power_w=3000.0, grid_power_w=500.0)
        acc = EnergyAccumulator()
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=30)
        data, _ = _run(raw=raw, acc=acc, last_update_time=last, now=now)
        # 30 min at 3kW solar = 1.5kWh
        assert data.today.solar_kwh == pytest.approx(1.5, rel=0.01)
        # 30 min at 500W import = 0.25kWh
        assert data.today.import_kwh == pytest.approx(0.25, rel=0.01)

    def test_battery_stats_updated(self):
        """Cycle count updates when SoC changes."""
        stats = BatteryStats()
        data, _ = _run(
            raw=_raw(battery_soc=60.0),
            battery_stats=stats,
            last_soc=80.0,  # 20% drop
        )
        assert data.battery_stats.total_cycles == pytest.approx(0.20)


class TestBuildCoordinatorDataNowDefault:
    def test_now_defaults_to_current_time(self):
        """When now=None, engine uses datetime.now(timezone.utc) without crashing."""
        raw = _raw()
        data, _ = build_coordinator_data(
            raw=raw,
            cfg=_nightboost_cfg(),
            acc=EnergyAccumulator(),
            battery_stats=BatteryStats(),
            last_soc=None,
            last_update_time=None,
            now=None,
        )
        assert isinstance(data, CoordinatorData)


class TestSkipChargeOverride:
    def test_override_skip_charge_sets_flag(self):
        data, _ = _run(override_skip_charge=True)
        assert data.charge_decision.skip_charge is True
        assert "skip" in data.charge_decision.reason.lower()

    def test_override_skip_charge_takes_priority_over_charge_target(self):
        """skip_charge override beats a manual charge target override."""
        data, _ = _run(override_skip_charge=True, override_charge_target=90)
        assert data.charge_decision.skip_charge is True

    def test_no_skip_by_default(self):
        """Without override, skip_charge follows forecast logic."""
        raw = _raw(battery_soc=20.0)
        data, _ = _run(raw=raw, override_skip_charge=False)
        # Low battery with no forecast should not skip
        assert data.charge_decision.skip_charge is False


class TestAccumulateEnergyLoadApportionment:
    """Tests for per-load cost apportionment added in the cleanup fix."""

    def _acc_after(self, raw_kwargs, elapsed_minutes=30):
        from datetime import datetime, timedelta

        from custom_components.givenergy_inverter_manager.core.engine import (
            accumulate_energy,
            build_tariff,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        raw = _raw(**raw_kwargs)
        acc = EnergyAccumulator()
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=elapsed_minutes)
        accumulate_energy(acc, raw, tariff, "Day", now, last)
        return acc

    def test_house_cost_populated_from_grid_import(self):
        """When only house load draws from grid, all import cost goes to house_cost."""
        acc = self._acc_after(
            {
                "grid_power_w": 1000.0,
                "house_load_w": 1000.0,
                "ev_power_w": 0.0,
            }
        )
        assert acc.house_cost > 0
        # zappi and immersion should be zero
        assert acc.zappi_cost == pytest.approx(0.0)
        assert acc.immersion_cost == pytest.approx(0.0)

    def test_zappi_cost_apportioned_by_load_fraction(self):
        """EV drawing 50% of house load gets 50% of import cost."""
        acc = self._acc_after(
            {
                "grid_power_w": 2000.0,
                "house_load_w": 2000.0,
                "ev_power_w": 1000.0,  # 50% of house load
            }
        )
        assert acc.zappi_cost > 0
        # zappi should be ~50% of total import cost
        total = acc.total_import_cost
        assert acc.zappi_cost == pytest.approx(total * 0.5, rel=0.01)

    def test_immersion_cost_apportioned(self):
        """Immersion drawing 30% of load gets ~30% of import cost."""
        acc = self._acc_after(
            {
                "grid_power_w": 1000.0,
                "house_load_w": 1000.0,
                "immersion_on": True,
                "immersion_wattage_w": 300.0,  # 30% of house load
            }
        )
        total = acc.total_import_cost
        assert acc.immersion_cost == pytest.approx(total * 0.3, rel=0.05)

    def test_house_cost_is_remainder(self):
        """house_cost + zappi_cost + immersion_cost should equal total import cost."""
        acc = self._acc_after(
            {
                "grid_power_w": 3000.0,
                "house_load_w": 3000.0,
                "ev_power_w": 1200.0,
                "immersion_on": True,
                "immersion_wattage_w": 600.0,
            }
        )
        total = acc.total_import_cost
        assert (acc.house_cost + acc.zappi_cost + acc.immersion_cost) == pytest.approx(
            total, rel=0.01
        )

    def test_no_cost_on_pure_solar(self):
        """When grid_power_w is zero (solar covers all), no costs are accumulated."""
        acc = self._acc_after(
            {
                "grid_power_w": 0.0,
                "solar_power_w": 5000.0,
                "house_load_w": 3000.0,
                "ev_power_w": 1000.0,
            }
        )
        assert acc.house_cost == pytest.approx(0.0)
        assert acc.zappi_cost == pytest.approx(0.0)
        assert acc.immersion_cost == pytest.approx(0.0)

    def test_battery_discharge_kwh_accumulated(self):
        """Battery discharging (negative battery_power_w) increments battery_discharge_kwh."""
        acc = self._acc_after(
            {
                "battery_power_w": -2000.0,  # discharging at 2kW
            }
        )
        # 30 min at 2kW = 1 kWh
        assert acc.battery_discharge_kwh == pytest.approx(1.0, rel=0.01)

    def test_battery_charge_does_not_increment_discharge(self):
        """Battery charging (positive battery_power_w) must not add to battery_discharge_kwh."""
        acc = self._acc_after(
            {
                "battery_power_w": 2000.0,  # charging
            }
        )
        assert acc.battery_discharge_kwh == pytest.approx(0.0)

    def test_self_sufficiency_with_battery_discharge(self):
        """Self-sufficiency should count battery discharge as local generation."""
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator(
            house_kwh=20.0,
            solar_kwh=12.0,
            battery_discharge_kwh=8.0,
            import_kwh=0.0,
        )
        # solar + battery discharge = 20kWh = 100% of consumption
        assert acc.self_sufficiency_pct == pytest.approx(100.0)


# ── Regression: cost apportionment overallocation ─────────────────────────────


class TestCostApportionmentNormalisation:
    """When EV + immersion loads exceed house_load_w, fractions must not exceed 1.0."""

    def test_no_overallocation_when_ev_plus_immersion_exceeds_house_load(self):
        """zappi_cost + immersion_cost + house_cost must never exceed period_cost."""
        from custom_components.givenergy_inverter_manager.core.engine import (
            accumulate_energy,
            build_tariff,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        # EV 2kW + immersion 2kW = 4kW, but house_load_w = 3kW
        raw = _raw(
            solar_power_w=0.0,
            grid_power_w=4000.0,
            house_load_w=3000.0,
            battery_power_w=0.0,
        )
        raw.ev_power_w = 2000.0
        raw.immersion_on = True
        raw.immersion_wattage_w = 2000.0

        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=30)

        accumulate_energy(acc, raw, tariff, "Day", now, last)

        # Total per-load costs must not exceed the total import cost
        total_allocated = acc.zappi_cost + acc.immersion_cost + acc.house_cost
        assert total_allocated <= acc.total_import_cost + 1e-9, (
            f"Overallocation: allocated={total_allocated:.6f} > import={acc.total_import_cost:.6f}"
        )

    def test_fractions_sum_to_one_when_normalised(self):
        """With equal EV and immersion exceeding house load, each gets half."""
        from custom_components.givenergy_inverter_manager.core.engine import (
            accumulate_energy,
            build_tariff,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        raw = _raw(
            solar_power_w=0.0,
            grid_power_w=3000.0,
            house_load_w=3000.0,
        )
        raw.ev_power_w = 3000.0  # EV = 100% of house load
        raw.immersion_on = True
        raw.immersion_wattage_w = 3000.0  # immersion = 100% of house load

        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 14, 0)
        last = now - timedelta(minutes=30)
        accumulate_energy(acc, raw, tariff, "Day", now, last)

        # With equal fractions normalised to 0.5 each:
        assert abs(acc.zappi_cost - acc.immersion_cost) < 1e-9
        assert acc.house_cost == pytest.approx(0.0)
        total = acc.zappi_cost + acc.immersion_cost + acc.house_cost
        assert total == pytest.approx(acc.total_import_cost, rel=1e-6)


# ── Regression: days_in_current_bill_period on start day ─────────────────────


class TestBillPeriodEdgeCases:
    def test_days_in_never_zero_on_billing_start_day(self):
        """On the billing start day, days_in must be 1, not 0."""
        from custom_components.givenergy_inverter_manager.core.tariff import TariffConfig

        tariff = TariffConfig(
            rate_periods=[],
            base_rate=0.3334,
            base_rate_name="Day",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=5.5,
            bill_start_day=16,
        )
        # 16th is billing start day
        days = tariff.days_in_current_bill_period(datetime(2024, 6, 16, 14, 0))
        assert days >= 1

    def test_projected_bill_not_inflated_on_start_day(self):
        """Projected bill on billing start day should be reasonable, not 30× accrued."""
        data, _ = _run(
            cfg={**_nightboost_cfg(), "bill_start_day": 16},
            now=datetime(2024, 6, 16, 14, 0),
        )
        # If days_in were 0, projected = accrued * days_remaining = huge
        # With the fix, days_in = 1, so projection is bounded
        assert data.projected_bill < data.accrued_bill * 40


# ── Regression: immersion min temp enforced ───────────────────────────────────


class TestImmersionMinTemp:
    def test_always_diverts_when_below_min_temp(self):
        """Should divert regardless of surplus when water is below minimum safe temp."""
        from custom_components.givenergy_inverter_manager.core.rules import (
            should_divert_to_immersion,
        )

        should, reason = should_divert_to_immersion(
            solar_power_w=0.0,  # no surplus at all
            house_load_w=2000.0,
            battery_soc=20.0,  # battery too low for normal divert
            battery_power_w=0.0,
            inverter_max_w=5000.0,
            immersion_temp=25.0,  # dangerously cold
            immersion_target_temp=55.0,
            immersion_min_temp=45.0,
            soc_threshold=80,
        )
        assert should is True
        assert "minimum" in reason.lower() or "below" in reason.lower()

    def test_no_min_temp_trigger_when_above_minimum(self):
        """Should not trigger the minimum-temp path when water is warm enough."""
        from custom_components.givenergy_inverter_manager.core.rules import (
            should_divert_to_immersion,
        )

        should, reason = should_divert_to_immersion(
            solar_power_w=0.0,
            house_load_w=2000.0,
            battery_soc=20.0,
            battery_power_w=0.0,
            inverter_max_w=5000.0,
            immersion_temp=48.0,  # above min_temp of 45°C
            immersion_target_temp=55.0,
            immersion_min_temp=45.0,
            soc_threshold=80,
        )
        # Falls through to battery-too-low check, not min_temp path
        assert should is False
        assert "minimum" not in reason.lower()


# ── New cost intelligence tracking ────────────────────────────────────────────


class TestImportRateBreakdown:
    """Import is split into cheap (timed period) vs peak (base rate) buckets."""

    def _run_import(self, rate_name: str, grid_w: float = 1000.0) -> EnergyAccumulator:
        from custom_components.givenergy_inverter_manager.core.engine import accumulate_energy
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        raw = _raw(grid_power_w=grid_w, solar_power_w=0.0)
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 2, 15, 2, 30, tzinfo=timezone.utc)  # Nightboost window
        last = datetime(2024, 2, 15, 2, 0, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, rate_name, now, last)
        return acc

    def test_cheap_import_counted_during_timed_period(self):
        acc = self._run_import("Nightboost")
        assert acc.import_kwh_cheap > 0
        assert acc.import_kwh_peak == 0.0

    def test_peak_import_counted_at_base_rate(self):
        acc = self._run_import("Day")
        assert acc.import_kwh_peak > 0
        assert acc.import_kwh_cheap == 0.0

    def test_cheap_fraction_sums_correctly(self):
        acc = self._run_import("Nightboost")
        assert abs(acc.import_kwh_cheap - acc.import_kwh) < 0.001

    def test_cost_split_matches_total(self):
        acc = self._run_import("Nightboost")
        assert abs((acc.import_cost_cheap + acc.import_cost_peak) - acc.total_import_cost) < 0.0001


class TestImmersionSavings:
    """Solar divert to immersion should record kWh and estimated savings."""

    def test_saves_when_solar_surplus_covers_immersion(self):
        from custom_components.givenergy_inverter_manager.core.engine import accumulate_energy
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        # Solar 5kW, house load 1kW, battery idle → 4kW surplus
        # Immersion 3kW running — all of it from solar
        raw = _raw(
            solar_power_w=5000.0,
            house_load_w=1000.0,
            battery_power_w=0.0,
            grid_power_w=0.0,
            immersion_on=True,
            immersion_wattage_w=3000.0,
        )
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 13, 0, tzinfo=timezone.utc)
        last = datetime(2024, 6, 15, 12, 30, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, "Day", now, last)

        assert acc.immersion_solar_kwh > 0, "Should have counted solar-to-immersion kWh"
        assert acc.immersion_savings > 0, "Should have savings when rate > export_rate"

    def test_no_savings_when_immersion_importing(self):
        from custom_components.givenergy_inverter_manager.core.engine import accumulate_energy
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        # No solar — immersion purely importing
        raw = _raw(
            solar_power_w=0.0,
            house_load_w=500.0,
            battery_power_w=0.0,
            grid_power_w=3500.0,
            immersion_on=True,
            immersion_wattage_w=3000.0,
        )
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 1, 15, 3, 0, tzinfo=timezone.utc)
        last = datetime(2024, 1, 15, 2, 30, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, "Night", now, last)

        assert acc.immersion_solar_kwh == 0.0, "No solar surplus → no solar divert"
        assert acc.immersion_savings == 0.0


class TestBatteryThroughput:
    """Battery throughput accumulates on both charge and discharge."""

    def test_throughput_on_discharge(self):
        from custom_components.givenergy_inverter_manager.core.engine import accumulate_energy
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        raw = _raw(battery_power_w=-2000.0)  # discharging
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc)
        last = datetime(2024, 6, 15, 13, 30, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, "Day", now, last)
        assert acc.battery_throughput_kwh > 0
        assert abs(acc.battery_throughput_kwh - acc.battery_discharge_kwh) < 0.001

    def test_throughput_on_charge(self):
        from custom_components.givenergy_inverter_manager.core.engine import accumulate_energy
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        raw = _raw(battery_power_w=2000.0)  # charging
        tariff = build_tariff(_nightboost_cfg())
        now = datetime(2024, 1, 15, 3, 0, tzinfo=timezone.utc)
        last = datetime(2024, 1, 15, 2, 30, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, "Nightboost", now, last)
        assert acc.battery_throughput_kwh > 0
        assert abs(acc.battery_throughput_kwh - acc.battery_charge_kwh) < 0.001


# ── HTML report generators ────────────────────────────────────────────────────


class TestReportGenerators:
    """reporting.py functions produce valid HTML from CoordinatorData."""

    def _data(self) -> CoordinatorData:
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        data, _ = _run()
        # Populate today accumulator with realistic values
        data.today.solar_kwh = 12.5
        data.today.import_kwh = 3.2
        data.today.export_kwh = 6.8
        data.today.import_kwh_cheap = 2.8
        data.today.import_kwh_peak = 0.4
        data.today.import_cost_by_period = {"Night": 0.46, "Day": 0.13}
        data.today.export_earnings = 1.33
        data.today.immersion_kwh = 2.0
        data.today.immersion_solar_kwh = 1.8
        data.today.immersion_savings = 0.25
        data.today.battery_throughput_kwh = 4.5
        data.accrued_bill = 2.30
        data.projected_bill = 28.50
        data.currency_symbol = "€"
        data.solar_forecast_kwh_today = 14.0
        data.battery_soc = 72.0
        data.charge_decision = ChargeDecision(
            target_soc=75,
            skip_charge=False,
            reason="Moderate forecast — charging to 75%.",
            forecast_kwh=14.0,
            current_soc=45.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=0.83,
        )
        return data

    def test_today_summary_html_contains_key_values(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_today_summary_html,
        )

        html = build_today_summary_html(self._data())
        assert "12.5" in html  # solar
        assert "3.2" in html  # import
        assert "€" in html  # currency
        assert "<table" in html

    def test_today_summary_state_is_short(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_today_summary_state,
        )

        state = build_today_summary_state(self._data())
        assert len(state) <= 255
        assert "Solar" in state

    def test_charge_plan_html_shows_target_soc(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_charge_plan_html,
        )

        html = build_charge_plan_html(self._data())
        assert "75" in html  # target SoC
        assert "14.0" in html  # forecast
        assert "Moderate" in html  # reason

    def test_charge_plan_html_skip_case(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_charge_plan_html,
        )
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        data = self._data()
        data.charge_decision = ChargeDecision(
            target_soc=25,
            skip_charge=True,
            reason="Battery at 85%, good solar forecast.",
            forecast_kwh=18.0,
            current_soc=85.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=0.0,
        )
        html = build_charge_plan_html(data)
        assert "Skip" in html

    def test_charge_plan_html_no_decision(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_charge_plan_html,
        )

        data = self._data()
        data.charge_decision = None
        html = build_charge_plan_html(data)
        assert "No charge decision" in html

    def test_week_summary_html_contains_week_data(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_week_summary_html,
        )

        data = self._data()
        data.week.solar_kwh = 65.3
        data.week.import_kwh_cheap = 14.2
        html = build_week_summary_html(data)
        assert "65.3" in html
        assert "14.2" in html
        assert "This Week" in html

    def test_forecast_accuracy_shown_in_week_summary(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_week_summary_html,
        )

        data = self._data()
        data.yesterday_forecast_accuracy_pct = 92.5
        html = build_week_summary_html(data)
        assert "92" in html

    def test_html_contains_css_class(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_today_summary_html,
        )

        html = build_today_summary_html(self._data())
        assert "ge-card" not in html  # class-based CSS removed; uses inline styles now
        assert "<style>" not in html  # removed — uses inline styles for HA Markdown card compat
        assert "style=" in html  # inline styles present instead


# ── _accumulate_energy: elapsed > 1h guard ───────────────────────────────────


class TestAccumulationElapsedGuard:
    def test_skips_accumulation_when_gap_exceeds_one_hour(self):
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        raw = _raw(solar_power_w=3000.0)
        cfg = _nightboost_cfg()
        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        stale = now - timedelta(hours=2)

        data1, _ = _run(raw=raw, cfg=cfg, now=stale)
        solar_before = data1.today.solar_kwh

        data2, _ = _run(raw=raw, cfg=cfg, now=now, last_update_time=stale)
        assert data2.today.solar_kwh == pytest.approx(solar_before, abs=0.01)


# ── _accumulate_energy: missed_solar ────────────────────────────────────────


class TestMissedSolarAccumulation:
    def test_accumulates_when_battery_full_and_exporting(self):
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=5)
        raw = _raw(
            battery_soc=100.0,
            grid_power_w=-1000.0,
            solar_power_w=4000.0,
            house_load_w=500.0,
            immersion_on=False,
            ev_power_w=0.0,
        )
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=last)
        assert data.today.missed_solar_kwh > 0.0

    def test_does_not_accumulate_when_battery_not_full(self):
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=5)
        raw = _raw(
            battery_soc=80.0,
            grid_power_w=-500.0,
            solar_power_w=3000.0,
        )
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=last)
        assert data.today.missed_solar_kwh == pytest.approx(0.0)


# ── EV charging source labels ────────────────────────────────────────────────


class TestEVChargingSourceLabels:
    def _zappi(self):
        from custom_components.givenergy_inverter_manager.discovery import (
            EVCharger,
            EVChargerBrand,
            EVChargerState,
        )

        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="123",
            display_name="Zappi (123)",
            state=EVChargerState.CHARGING,
            charge_mode="Eco+",
            charge_mode_entity="select.zappi_123_charge_mode",
        )
        ch.power_w = 2000.0
        return ch

    def _run_with(self, grid_w, batt_w, ev_w=2000.0):
        from tests.conftest import _nightboost_cfg, _raw, _run

        ch = self._zappi()
        ch.power_w = ev_w
        raw = _raw(grid_power_w=grid_w, battery_power_w=batt_w, ev_power_w=ev_w, ev_plugged_in=True)
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), ev_charger=ch)
        return data.ev_charging_source

    def test_solar_when_grid_importing_and_battery_charging(self):
        assert self._run_with(grid_w=-100.0, batt_w=500.0) == "Solar"

    def test_battery_when_grid_exporting_and_battery_discharging(self):
        assert self._run_with(grid_w=-100.0, batt_w=-500.0) == "Battery"

    def test_grid_when_importing_and_battery_idle(self):
        assert self._run_with(grid_w=800.0, batt_w=0.0) == "Grid"

    def test_mixed_when_importing_and_battery_discharging(self):
        assert self._run_with(grid_w=800.0, batt_w=-300.0) == "Mixed"


# ── override_skip_charge ────────────────────────────────────────────────────


class TestOverrideSkipCharge:
    def test_skip_charge_override_sets_skip_true(self):
        from tests.conftest import _nightboost_cfg, _raw, _run

        raw = _raw(battery_soc=40.0)
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), override_skip_charge=True)
        assert data.charge_decision is not None
        assert data.charge_decision.skip_charge is True
        assert "manual" in data.charge_decision.reason.lower()


# ── Reporting: build_charge_plan_state skip branch ──────────────────────────


class TestReportingGaps:
    def _data(self):
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
        from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
        from custom_components.givenergy_inverter_manager.discovery.ev_charger import EVChargerState

        data = CoordinatorData()
        data.today = EnergyAccumulator()
        data.week = EnergyAccumulator()
        data.month = EnergyAccumulator()
        data.yesterday = EnergyAccumulator()
        data.battery_stats = BatteryStats()
        data.currency_symbol = "€"
        data.ev_available = False
        data.ev_charger_state = EVChargerState.UNKNOWN
        data.ev_charger_name = ""
        data.ev_power_w = 0.0
        data.ev_draining_battery = False
        data.ev_protection_reason = ""
        data.charge_decision = ChargeDecision(
            target_soc=80,
            skip_charge=True,
            reason="Good forecast",
            forecast_kwh=12.0,
            current_soc=75.0,
            battery_capacity=10.0,
            car_plugged_in=False,
            cost_to_charge=0.0,
        )
        data.should_divert_immersion = False
        data.divert_reason = ""
        data.will_survive_night = True
        data.survival_reason = ""
        data.accrued_bill = 0.0
        data.projected_bill = 0.0
        data.days_remaining = 15
        data.days_in_period = 30
        data.forecast_kwh_tomorrow = None
        data.solar_forecast_kwh_today = 0.0
        data.yesterday_forecast_accuracy_pct = 0.0
        data.forecast_accuracy_7day_avg_pct = 0.0
        return data

    def test_charge_plan_state_shows_skip_when_skipping(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_charge_plan_state,
        )

        data = self._data()
        state = build_charge_plan_state(data)
        assert "Skip" in state
        assert "12.0" in state

    def test_week_summary_shows_7day_accuracy_when_present(self):
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_week_summary_html,
        )

        data = self._data()
        data.forecast_accuracy_7day_avg_pct = 88.0
        html = build_week_summary_html(data)
        assert "88" in html


# ── _apply_daily_counters (GivTCP energy precision) ──────────────────────────


class TestApplyDailyCounters:
    """GivTCP daily energy counters override integration when present."""

    def _run_with_counters(self, **counter_kwargs):
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        now = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=5)
        raw = _raw(
            solar_power_w=3000.0,
            grid_power_w=-500.0,
            battery_power_w=500.0,
        )
        for key, value in counter_kwargs.items():
            setattr(raw, key, value)
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=last)
        return data

    def test_solar_counter_overrides_integration(self):
        data = self._run_with_counters(solar_energy_today_kwh=12.5)
        assert data.today.solar_kwh == pytest.approx(12.5)

    def test_import_counter_overrides_integration(self):
        data = self._run_with_counters(import_energy_today_kwh=4.2)
        assert data.today.import_kwh == pytest.approx(4.2)

    def test_export_counter_overrides_integration(self):
        data = self._run_with_counters(export_energy_today_kwh=7.8)
        assert data.today.export_kwh == pytest.approx(7.8)

    def test_battery_charge_counter_overrides_integration(self):
        data = self._run_with_counters(charge_energy_today_kwh=3.1)
        assert data.today.battery_charge_kwh == pytest.approx(3.1)

    def test_battery_discharge_counter_overrides_integration(self):
        data = self._run_with_counters(discharge_energy_today_kwh=2.9)
        assert data.today.battery_discharge_kwh == pytest.approx(2.9)

    def test_load_counter_overrides_integration(self):
        data = self._run_with_counters(load_energy_today_kwh=9.3)
        assert data.today.house_kwh == pytest.approx(9.3)

    def test_none_counter_preserves_integration_value(self):
        """When counter is None, integration value is kept."""
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        now = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=5)
        raw = _raw(solar_power_w=3000.0)
        raw.solar_energy_today_kwh = None
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=last)
        assert data.today.solar_kwh > 0.0

    def test_financial_fields_not_overridden_by_counters(self):
        """Costs come from integration (GivTCP has no tariff knowledge)."""
        from datetime import datetime, timedelta, timezone

        from tests.conftest import _nightboost_cfg, _raw, _run

        now = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=5)
        raw = _raw(grid_power_w=2000.0)
        raw.import_energy_today_kwh = 99.9
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=last)
        assert data.today.import_kwh == pytest.approx(99.9)
        total_cost = sum(data.today.import_cost_by_period.values())
        assert total_cost > 0
