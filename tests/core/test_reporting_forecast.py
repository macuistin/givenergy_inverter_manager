"""The today report judges the day against the provider's forecast, as the dashboard does.

The charge plan's forecast is blended toward the pessimistic estimate and scaled by the accuracy
correction. It stays in the charge plan report, labelled as the plan's.
"""

from __future__ import annotations

import re

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.core import reporting
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

_FORECAST_DETAIL = re.compile(r"Forecast: ([\d.]+)kWh \((\d+)%\)")


def _data(*, raw: float | None, plan: float, solar: float) -> CoordinatorData:
    data = CoordinatorData()
    data.solar_forecast_raw_kwh_today = raw
    data.solar_forecast_kwh_today = plan
    data.today = EnergyAccumulator(solar_kwh=solar)
    return data


def _decision(forecast_kwh: float) -> ChargeDecision:
    return ChargeDecision(
        target_soc=60,
        skip_charge=False,
        reason="Charge",
        forecast_kwh=forecast_kwh,
        current_soc=30.0,
        battery_capacity=9.5,
        car_plugged_in=False,
        cost_to_charge=1.2,
    )


class TestTodayReportForecastLine:
    def test_uses_the_provider_forecast_and_percentage(self):
        """Live case: the plan held 31.5 kWh against the provider's 38.96."""
        html = reporting.build_today_summary_html(_data(raw=38.96, plan=31.5, solar=20.0))
        assert "Forecast: 39.0kWh (51%)" in html

    def test_ignores_the_blended_charge_plan_forecast(self):
        html = reporting.build_today_summary_html(_data(raw=10.0, plan=4.0, solar=7.5))
        assert "Forecast: 10.0kWh (75%)" in html
        assert "4.0kWh" not in html

    def test_leaves_the_line_out_without_a_provider_forecast(self):
        """A plan forecast alone, such as the seasonal estimate, is not a provider forecast."""
        html = reporting.build_today_summary_html(_data(raw=None, plan=31.5, solar=7.5))
        assert "Forecast" not in html
        assert "31.5" not in html

    def test_leaves_the_line_out_for_a_zero_provider_forecast(self):
        html = reporting.build_today_summary_html(_data(raw=0.0, plan=31.5, solar=7.5))
        assert "Forecast" not in html

    def test_reads_zero_percent_before_any_solar(self):
        html = reporting.build_today_summary_html(_data(raw=38.96, plan=31.5, solar=0.0))
        assert "Forecast: 39.0kWh (0%)" in html

    def test_does_not_cap_a_day_that_beats_the_forecast(self):
        html = reporting.build_today_summary_html(_data(raw=10.0, plan=10.0, solar=35.0))
        assert "Forecast: 10.0kWh (350%)" in html

    @pytest.mark.parametrize(
        ("raw", "solar"),
        [(38.96, 20.0), (38.96, 45.0), (10.0, 7.5), (6.2, 0.3), (14.0, 35.0), (22.5, 22.5)],
    )
    def test_agrees_with_the_dashboard_sensor(self, raw, solar):
        data = _data(raw=raw, plan=raw * 0.8, solar=solar)
        shown = _FORECAST_DETAIL.search(reporting.build_today_summary_html(data))
        assert float(shown.group(1)) == pytest.approx(
            values.solar_forecast_raw_today(data), abs=0.05
        )
        assert int(shown.group(2)) == round(values.solar_actual_vs_forecast_pct(data))


class TestChargePlanForecastLabel:
    def test_html_row_is_labelled_as_the_plans(self):
        data = _data(raw=38.96, plan=31.5, solar=0.0)
        data.charge_decision = _decision(31.5)
        html = reporting.build_charge_plan_html(data)
        assert "Plan forecast" in html
        assert "Solar forecast" not in html

    def test_skip_state_names_the_plans_forecast(self):
        data = _data(raw=38.96, plan=31.5, solar=0.0)
        decision = _decision(31.5)
        data.charge_decision = ChargeDecision(**{**decision.__dict__, "skip_charge": True})
        assert (
            reporting.build_charge_plan_state(data)
            == "Skip charge · Plan forecast 31.5 kWh · SoC 30%"
        )


def test_week_and_yesterday_sections_carry_no_forecast_line_of_their_own():
    """Their accuracy rows already measure against the provider's forecast (see accumulation)."""
    html = reporting.build_week_summary_html(_data(raw=38.96, plan=31.5, solar=20.0))
    assert "Forecast:" not in html
