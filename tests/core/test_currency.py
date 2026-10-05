"""The configured currency reaches reason strings and reports. EUR output is unchanged."""

import pytest

from custom_components.givenergy_inverter_manager.core import reporting
from custom_components.givenergy_inverter_manager.core.rules import (
    should_divert_to_immersion,
    suggest_appliance_run,
)
from tests.conftest import _nightboost_cfg, _raw, _run


def _appliance(**overrides):
    kwargs = {
        "solar_power_w": 4000.0,
        "house_load_w": 500.0,
        "battery_soc": 85.0,
        "battery_power_w": 0.0,
        "appliance_power_w": 2000.0,
        "appliance_name": "Washing Machine",
        "rate_period_name": "Day",
        "rate": 0.3334,
        "export_rate": 0.195,
    }
    kwargs.update(overrides)
    return suggest_appliance_run(**kwargs)


# Each case reaches a different reason string: surplus, battery, expensive.
_APPLIANCE_CASES = {
    "surplus": {},
    "battery": {"solar_power_w": 0.0, "house_load_w": 0.0, "rate": 0.2},
    "expensive": {"solar_power_w": 0.0, "house_load_w": 0.0, "battery_soc": 10.0},
}


class TestApplianceReasonCurrency:
    @pytest.mark.parametrize("case", _APPLIANCE_CASES)
    def test_gbp_reason_uses_pound(self, case):
        _, reason = _appliance(**_APPLIANCE_CASES[case], currency_symbol="£")
        assert "£" in reason
        assert "€" not in reason

    @pytest.mark.parametrize("case", _APPLIANCE_CASES)
    def test_default_is_euro(self, case):
        _, reason = _appliance(**_APPLIANCE_CASES[case])
        assert "€" in reason

    def test_euro_reason_text_is_unchanged(self):
        _, reason = _appliance(**_APPLIANCE_CASES["surplus"], currency_symbol="€")
        assert reason == (
            "Good time to run Washing Machine: 3500W surplus available. "
            "Running now saves ~€0.667 vs grid rate."
        )


def _divert(**overrides):
    kwargs = {
        "solar_power_w": 4000.0,
        "house_load_w": 500.0,
        "battery_soc": 90.0,
        "battery_power_w": 0.0,
        "inverter_max_w": 5000.0,
        "immersion_temp": 40.0,
        "immersion_target_temp": 55.0,
        "immersion_min_temp": 30.0,
        "battery_cycle_cost_per_kwh": 0.30,
        "export_rate": 0.195,
    }
    kwargs.update(overrides)
    return should_divert_to_immersion(**kwargs)


class TestDivertReasonCurrency:
    def test_gbp_cycle_cost_reason_uses_pound(self):
        diverted, reason = _divert(currency_symbol="£")
        assert diverted is False
        assert "£/kWh" in reason
        assert "€" not in reason

    def test_euro_reason_text_is_unchanged(self):
        _, reason = _divert()
        assert reason == (
            "Export rate 0.1950 €/kWh is below battery cycle cost "
            "0.3000 €/kWh — not worth cycling"
        )


class TestEngineThreadsTheSymbol:
    @staticmethod
    def _cfg(currency):
        cfg = _nightboost_cfg()
        cfg["currency"] = currency
        cfg["battery_cost_eur"] = 50000.0
        return cfg

    @staticmethod
    def _raw_with_surplus():
        return _raw(
            solar_power_w=4000.0,
            house_load_w=500.0,
            battery_soc=90.0,
            battery_power_w=0.0,
            battery_capacity_kwh=10.0,
        )

    def test_gbp_config_gives_pound_in_the_divert_reason(self):
        data, _ = _run(raw=self._raw_with_surplus(), cfg=self._cfg("GBP"))
        assert data.currency_symbol == "£"
        assert "£/kWh" in data.divert_reason
        assert "€" not in data.divert_reason

    def test_eur_config_is_unchanged(self):
        data, _ = _run(raw=self._raw_with_surplus(), cfg=self._cfg("EUR"))
        assert data.currency_symbol == "€"
        assert "€/kWh" in data.divert_reason


class TestReportsUseTheConfiguredSymbol:
    @staticmethod
    def _data(symbol):
        data, _ = _run()
        data.currency_symbol = symbol
        data.today.import_kwh = 3.0
        data.today.export_earnings = 1.2
        data.week.import_kwh = 20.0
        data.week.export_earnings = 7.0
        data.accrued_bill = 12.0
        data.projected_bill = 30.0
        return data

    @pytest.mark.parametrize(
        "builder",
        [
            reporting.build_today_summary_html,
            reporting.build_today_summary_state,
            reporting.build_charge_plan_html,
            reporting.build_week_summary_html,
        ],
    )
    def test_gbp_reports_have_no_euro(self, builder):
        text = builder(self._data("£"))
        assert "£" in text
        assert "€" not in text

    @pytest.mark.parametrize(
        "builder",
        [
            reporting.build_today_summary_html,
            reporting.build_today_summary_state,
            reporting.build_charge_plan_html,
            reporting.build_week_summary_html,
        ],
    )
    def test_eur_reports_still_use_euro(self, builder):
        assert "€" in builder(self._data("€"))
