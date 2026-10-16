"""Tomorrow's outlook: the plan's own simulated day, priced slot by slot.

The day is the one calculate_overnight_charge_target simulates (planned_day), started from the
level tonight's charge leaves and held between the minimum SoC and full. Each check uses a flat
load of 0.1 kWh a half hour on a 10 kWh battery, so one slot moves the battery one point.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
    DEFAULT_RATE_PERIODS,
)
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeDecision,
    ChargeInputs,
    SolarForecast,
    _simulate_min_soc,
    calculate_overnight_charge_target,
    monthly_solar_fractions,
    planned_day,
)
from custom_components.givenergy_inverter_manager.core.tariff import RatePeriod, TariffConfig
from custom_components.givenergy_inverter_manager.core.tomorrow_outlook import (
    OutlookInputs,
    TomorrowOutlook,
    outlook_table,
    project_outlook,
)
from tests.conftest import _nightboost_cfg, _raw, _run

CAPACITY_KWH = 10.0
DAILY_LOAD_KWH = 4.8  # 0.1 kWh a slot, one point of the battery
FLOOR_PCT = 10.0
SUMMER = datetime(2031, 6, 14, 21, 0)
ON = date(2031, 6, 15)
NIGHT_RATE, DAY_RATE, EXPORT_RATE = 0.20, 0.40, 0.20
MINUS = "‑"


def _tariff(vat_pct: float = 0.0, discount_pct: float = 0.0) -> TariffConfig:
    return TariffConfig(
        rate_periods=[RatePeriod("Night", NIGHT_RATE, time(23, 0), time(8, 0))],
        base_rate=DAY_RATE,
        base_rate_name="Day",
        export_rate=EXPORT_RATE,
        standing_charge=0.0,
        pso_levy=0.0,
        vat_rate=vat_pct,
        discount_rate=discount_pct,
        bill_start_day=1,
    )


def _inputs(pause: PauseWindow | None = None, capacity_kwh: float = CAPACITY_KWH) -> ChargeInputs:
    return ChargeInputs(
        current_soc=60.0,
        battery_capacity_kwh=capacity_kwh,
        min_soc=int(FLOOR_PCT),
        skip_charge_threshold=75,
        car_plugged_in=False,
        inverter_max_kw=5.0,
        average_daily_consumption_kwh=DAILY_LOAD_KWH,
        cheapest_rate=NIGHT_RATE,
        battery_pause=pause,
    )


def _decision(current_soc: float, target_soc: int, skip: bool = False) -> ChargeDecision:
    kwh = 0.0 if skip else max(0.0, CAPACITY_KWH * (target_soc - current_soc) / 100)
    return ChargeDecision(
        target_soc=target_soc,
        skip_charge=skip,
        reason="",
        forecast_kwh=0.0,
        current_soc=current_soc,
        battery_capacity=CAPACITY_KWH,
        car_plugged_in=False,
        cost_to_charge=kwh * NIGHT_RATE,
    )


def _outlook(
    decision: ChargeDecision,
    forecast_kwh: float,
    pause: PauseWindow | None = None,
    tariff: TariffConfig | None = None,
) -> TomorrowOutlook:
    day = planned_day(_inputs(pause), SolarForecast(forecast_kwh=forecast_kwh), SUMMER)
    assert day is not None
    return project_outlook(
        OutlookInputs(
            day=day, decision=decision, tariff=tariff or _tariff(), on=ON, floor_pct=FLOOR_PCT
        )
    )


def _assert_energy_balances(outlook: TomorrowOutlook, start_soc_pct: float) -> None:
    """Grid in less grid out is the load, less solar, plus what the battery gained."""
    stored_kwh = (outlook.end_soc_pct - start_soc_pct) * CAPACITY_KWH / 100
    assert outlook.import_kwh - outlook.export_kwh == pytest.approx(
        DAILY_LOAD_KWH - outlook.forecast_kwh + stored_kwh
    )


class TestSunnyDay:
    def test_exports_the_surplus_once_the_battery_is_full_and_imports_nothing(self):
        decision = _decision(current_soc=40.0, target_soc=50)
        outlook = _outlook(decision, forecast_kwh=30.0)
        assert outlook.import_kwh == 0.0
        assert outlook.import_cost == 0.0
        assert outlook.export_kwh > 20.0
        assert outlook.export_credit == round(outlook.export_kwh * EXPORT_RATE, 2)
        _assert_energy_balances(outlook, start_soc_pct=50.0)

    def test_ends_the_day_full_less_the_evening_load(self):
        """The bell curve ends with the 19:30 slot, so 20:00 to midnight runs the battery down."""
        outlook = _outlook(_decision(current_soc=40.0, target_soc=50), forecast_kwh=30.0)
        assert outlook.end_soc_pct == pytest.approx(92.0)

    def test_net_cost_is_the_charge_less_the_export_credit(self):
        outlook = _outlook(_decision(current_soc=40.0, target_soc=50), forecast_kwh=30.0)
        assert outlook.charge_kwh == pytest.approx(1.0)
        assert outlook.charge_cost == pytest.approx(0.2)
        assert outlook.net_cost == round(0.2 - outlook.export_credit, 2)
        assert outlook.net_cost < 0


class TestDullDay:
    def test_imports_the_whole_load_at_the_night_and_day_rates(self):
        """No solar and the battery at its floor: 18 night slots at 0.20, 30 day slots at 0.40."""
        decision = _decision(current_soc=FLOOR_PCT, target_soc=20, skip=True)
        outlook = _outlook(decision, forecast_kwh=0.0)
        assert outlook.import_kwh == pytest.approx(DAILY_LOAD_KWH)
        assert outlook.import_cost == pytest.approx(0.1 * (18 * NIGHT_RATE + 30 * DAY_RATE))
        assert outlook.export_kwh == 0.0
        assert outlook.min_soc_pct == FLOOR_PCT
        _assert_energy_balances(outlook, start_soc_pct=FLOOR_PCT)

    def test_import_is_priced_with_discount_and_vat_like_the_cost_sensors(self):
        decision = _decision(current_soc=FLOOR_PCT, target_soc=20, skip=True)
        outlook = _outlook(decision, forecast_kwh=0.0, tariff=_tariff(vat_pct=10.0))
        assert outlook.import_cost == round(1.56 * 1.1, 2)

    def test_the_battery_covers_the_night_then_the_grid_the_rest_at_the_day_rate(self):
        """From 30% the battery lasts 20 slots, to 10:00. The other 28 slots are on the grid."""
        decision = _decision(current_soc=30.0, target_soc=30)
        outlook = _outlook(decision, forecast_kwh=0.0)
        assert outlook.import_kwh == pytest.approx(2.8)
        assert outlook.import_cost == pytest.approx(0.1 * (26 * DAY_RATE + 2 * NIGHT_RATE))
        _assert_energy_balances(outlook, start_soc_pct=30.0)


class TestTonightsCharge:
    def test_a_skipped_night_starts_from_the_level_now_and_adds_no_charge(self):
        outlook = _outlook(_decision(current_soc=60.0, target_soc=20, skip=True), 0.0)
        assert outlook.charge_kwh == 0.0
        assert outlook.charge_cost == 0.0
        assert outlook.end_soc_pct == pytest.approx(12.0)

    def test_a_charge_night_starts_from_the_target(self):
        outlook = _outlook(_decision(current_soc=60.0, target_soc=80), 0.0)
        assert outlook.charge_kwh == pytest.approx(2.0)
        assert outlook.charge_cost == pytest.approx(0.4)
        assert outlook.end_soc_pct == pytest.approx(32.0)

    def test_a_battery_above_its_target_starts_where_it_is(self):
        outlook = _outlook(_decision(current_soc=70.0, target_soc=50), 0.0)
        assert outlook.charge_kwh == 0.0
        assert outlook.end_soc_pct == pytest.approx(22.0)

    def test_the_charge_cost_is_the_plans_own_figure(self):
        decision = _decision(current_soc=60.0, target_soc=80)
        assert _outlook(decision, 0.0).charge_cost == round(decision.cost_to_charge, 2)


class TestBatteryPause:
    def test_the_paused_hours_run_on_the_grid_and_the_battery_holds(self):
        """Paused 00:00 to 08:00: 16 slots from the grid at the night rate, 32 from the battery."""
        decision = _decision(current_soc=60.0, target_soc=20, skip=True)
        outlook = _outlook(decision, 0.0, pause=PauseWindow(time(0, 0), time(8, 0)))
        assert outlook.import_kwh == pytest.approx(1.6)
        assert outlook.import_cost == pytest.approx(1.6 * NIGHT_RATE)
        assert outlook.end_soc_pct == pytest.approx(28.0)
        _assert_energy_balances(outlook, start_soc_pct=60.0)

    def test_solar_still_charges_the_battery_in_a_paused_slot(self):
        decision = _decision(current_soc=40.0, target_soc=50)
        paused = _outlook(decision, 30.0, pause=PauseWindow(time(10, 0), time(16, 0)))
        assert paused.export_kwh == pytest.approx(_outlook(decision, 30.0).export_kwh)


class TestTheSameModelAsThePlan:
    def test_the_lowest_level_is_the_one_the_plan_simulated(self):
        inputs = replace(_inputs(), current_soc=5.0)
        forecast = SolarForecast(forecast_kwh=6.0)
        decision = calculate_overnight_charge_target(inputs, forecast, SUMMER)
        day = planned_day(inputs, forecast, SUMMER)
        assert not decision.skip_charge
        outlook = project_outlook(OutlookInputs(day, decision, _tariff(), ON, FLOOR_PCT))
        assert outlook.min_soc_pct == pytest.approx(
            _simulate_min_soc(decision.target_soc, day.model)
        )
        assert outlook.forecast_kwh == pytest.approx(decision.forecast_kwh)

    def test_the_forecast_is_resolved_with_the_accuracy_correction(self):
        forecast = SolarForecast(forecast_kwh=10.0, forecast_correction=0.8)
        assert planned_day(_inputs(), forecast, SUMMER).forecast_kwh == pytest.approx(8.0)


class TestNoProjection:
    def test_none_without_a_battery_capacity(self):
        assert planned_day(_inputs(capacity_kwh=0.0), SolarForecast(8.0), SUMMER) is None

    def test_none_with_no_forecast_and_nothing_to_estimate_one_from(self):
        assert planned_day(_inputs(), SolarForecast(forecast_kwh=None), SUMMER) is None

    def test_the_seasonal_estimate_is_used_and_named(self):
        forecast = SolarForecast(forecast_kwh=None, solar_fractions=monthly_solar_fractions(53))
        outlook = project_outlook(
            OutlookInputs(
                planned_day(_inputs(), forecast, SUMMER), _decision(60.0, 60), _tariff(), ON, 10
            )
        )
        assert outlook.basis == (
            f"Forecast {outlook.forecast_kwh:.1f} kWh from the seasonal estimate, "
            "the flat daily average load."
        )

    def test_the_basis_names_the_forecast_and_the_per_slot_profile(self):
        inputs = replace(_inputs(), load_profile=[0.1] * 48)
        day = planned_day(inputs, SolarForecast(forecast_kwh=25.74), SUMMER)
        outlook = project_outlook(OutlookInputs(day, _decision(60.0, 60), _tariff(), ON, 10))
        assert outlook.basis == (
            "Forecast 25.7 kWh from the forecast integration, the per-slot load profile."
        )


def _example(**changes) -> TomorrowOutlook:
    figures = {
        "on": ON,
        "forecast_kwh": 25.7,
        "import_kwh": 3.1,
        "export_kwh": 9.4,
        "import_cost": 0.58,
        "export_credit": 1.83,
        "charge_kwh": 0.0,
        "charge_cost": 0.0,
        "end_soc_pct": 80.0,
        "min_soc_pct": 20.0,
        "basis": "",
    }
    return TomorrowOutlook(**{**figures, **changes})


class TestTable:
    def test_the_table_text(self):
        assert outlook_table(_example(), "€") == (
            "| | Energy | Cost |\n"
            "|:--|--:|--:|\n"
            "| From the grid | 3.1 kWh | €0.58 |\n"
            "| Charge tonight | 0.0 kWh | €0.00 |\n"
            f"| To the grid | 9.4 kWh | {MINUS}€1.83 |\n"
            f"| **Tomorrow** | | **{MINUS}€1.25** |"
        )

    def test_a_cost_overall_has_no_sign_and_nothing_exported_is_not_negative(self):
        table = outlook_table(_example(export_kwh=0.0, export_credit=0.0), "£")
        assert "| To the grid | 0.0 kWh | £0.00 |" in table
        assert "| **Tomorrow** | | **£0.58** |" in table
        assert MINUS not in table

    def test_energy_is_shown_to_one_decimal_place(self):
        table = outlook_table(_example(import_kwh=3.149, export_kwh=12.06), "€")
        assert "| From the grid | 3.1 kWh |" in table
        assert "| To the grid | 12.1 kWh |" in table


class TestRounding:
    def test_money_is_in_cents_and_the_net_is_the_sum_of_the_lines(self):
        decision = _decision(current_soc=FLOOR_PCT, target_soc=20, skip=True)
        outlook = _outlook(decision, 0.0, tariff=_tariff(vat_pct=13.5, discount_pct=5.5))
        assert outlook.import_cost == round(outlook.import_cost, 2)
        assert outlook.net_cost == round(
            outlook.import_cost + outlook.charge_cost - outlook.export_credit, 2
        )

    def test_a_net_of_nothing_is_not_negative_zero(self):
        outlook = _example(import_cost=0.0, export_credit=0.0)
        assert str(outlook.net_cost) == "0.0"
        assert "**€0.00**" in outlook_table(outlook, "€")


DAY_BEFORE_CHANGE = datetime(2031, 10, 5, 21, 0)


def _engine_outlook(now: datetime, cfg: dict | None = None) -> CoordinatorData:
    raw = _raw(battery_soc=20.0, battery_capacity_kwh=3.0, forecast_kwh_tomorrow=0.5)
    data, _ = _run(raw=raw, cfg=cfg, now=now, today_raw_forecast_kwh=0.5)
    return data


def _with_change(effective: date) -> dict:
    change = {
        "effective": effective.isoformat(),
        CONF_BASE_RATE: 0.80,
        CONF_BASE_RATE_NAME: "Day",
        CONF_EXPORT_RATE: 0.195,
        CONF_RATE_PERIODS: DEFAULT_RATE_PERIODS,
    }
    return {**_nightboost_cfg(), CONF_TARIFF_CHANGES: [change]}


class TestThroughTheEngine:
    def test_before_midnight_the_day_is_tomorrow(self):
        assert _engine_outlook(DAY_BEFORE_CHANGE).tomorrow_outlook.on == date(2031, 10, 6)

    def test_from_midnight_to_sunrise_the_day_is_today(self):
        data = _engine_outlook(datetime(2031, 10, 6, 1, 0))
        assert data.tomorrow_outlook.on == date(2031, 10, 6)

    def test_the_charge_cost_agrees_with_the_estimated_overnight_charge_cost(self):
        data = _engine_outlook(DAY_BEFORE_CHANGE)
        assert data.tomorrow_outlook.charge_cost == round(values.overnight_charge_cost(data), 2)
        assert data.tomorrow_outlook.charge_cost > 0

    def test_a_tariff_change_that_starts_tomorrow_prices_tomorrow(self):
        plain = _engine_outlook(DAY_BEFORE_CHANGE).tomorrow_outlook
        changed = _engine_outlook(DAY_BEFORE_CHANGE, _with_change(date(2031, 10, 6)))
        assert changed.tomorrow_outlook.import_cost > plain.import_cost > 0
        assert changed.tomorrow_outlook.charge_cost == plain.charge_cost

    def test_a_change_that_starts_after_the_day_does_not_count(self):
        plain = _engine_outlook(DAY_BEFORE_CHANGE).tomorrow_outlook
        later = _engine_outlook(DAY_BEFORE_CHANGE, _with_change(date(2031, 10, 7)))
        assert later.tomorrow_outlook.import_cost == plain.import_cost

    def test_no_outlook_with_no_forecast_and_no_seasonal_fractions(self):
        raw = _raw(battery_capacity_kwh=3.0, forecast_kwh_tomorrow=None)
        data, _ = _run(raw=raw, now=DAY_BEFORE_CHANGE)
        assert data.tomorrow_outlook is None
        assert values.tomorrow_outlook_cost(data) is None
        assert values.tomorrow_outlook_attributes(data) is None
