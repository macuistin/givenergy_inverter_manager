"""The water heating advice through the engine: when it exists and what it reads."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from custom_components.givenergy_inverter_manager.const import (
    OIL_BOILER_EFFICIENCY_PCT,
    OIL_KWH_PER_LITRE,
)
from custom_components.givenergy_inverter_manager.core.oil_advice import (
    SOURCE_ELECTRICITY,
    SOURCE_OIL,
    SOURCE_SOLAR,
)
from tests.conftest import _raw, _run

CFG = {
    "base_rate": 0.30,
    "export_rate": 0.15,
    "vat_rate": 0,
    "discount_rate": 0,
    "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
}


def price_for(cost_per_kwh: float) -> float:
    """The price of a litre that costs this much per kWh of heat."""
    return cost_per_kwh * OIL_KWH_PER_LITRE * OIL_BOILER_EFFICIENCY_PCT / 100


def advice_at(hour: int, **raw):
    fields = {"solar_power_w": 0.0, "house_load_w": 400.0, "battery_soc": 20.0}
    fields.update(raw)
    data = _run(raw=_raw(**fields), cfg=CFG, now=datetime(2026, 12, 15, hour))[0]
    return data.water_heating_advice


class TestWhenThereIsAdvice:
    def test_with_no_oil_price_nothing_is_worked_out(self):
        assert advice_at(12) is None

    def test_with_a_price_the_advice_compares_it_with_the_tariff(self):
        advice = advice_at(12, oil_price_per_litre=price_for(0.20))
        assert advice.source == SOURCE_OIL
        assert advice.oil_cost_per_kwh == pytest.approx(0.20)
        assert advice.electricity_cost_per_kwh == pytest.approx(0.30)

    def test_in_the_cheap_window_electricity_is_the_cheaper_source(self):
        assert advice_at(1, oil_price_per_litre=price_for(0.20)).source == SOURCE_ELECTRICITY

    def test_a_dearer_oil_price_changes_the_advice_on_the_next_cycle(self):
        assert advice_at(12, oil_price_per_litre=price_for(0.40)).source == SOURCE_ELECTRICITY


class TestWhatItReads:
    def test_the_currency_is_the_configured_one(self):
        data = _run(
            raw=_raw(oil_price_per_litre=price_for(0.20)),
            cfg={**CFG, "currency": "GBP"},
            now=datetime(2026, 12, 15, 12),
        )[0]
        assert "£" in data.water_heating_advice.suggestion

    def test_a_surplus_the_immersion_would_divert_is_solar(self):
        advice = advice_at(
            12, solar_power_w=4500.0, battery_soc=95.0, oil_price_per_litre=price_for(0.20)
        )
        assert advice.source == SOURCE_SOLAR

    def test_a_surplus_with_the_battery_below_the_divert_level_is_not_solar(self):
        advice = advice_at(
            12, solar_power_w=4500.0, battery_soc=20.0, oil_price_per_litre=price_for(0.20)
        )
        assert advice.source == SOURCE_OIL

    def test_a_small_surplus_is_not_solar(self):
        advice = advice_at(
            12, solar_power_w=450.0, battery_soc=95.0, oil_price_per_litre=price_for(0.20)
        )
        assert advice.source == SOURCE_OIL

    def test_the_ready_times_set_the_horizon_even_with_scheduled_heating_off(self):
        advice = advice_at(
            12,
            oil_price_per_litre=price_for(0.20),
            immersion_ready_times=(time(7, 0),),
            immersion_schedule_enabled=False,
        )
        assert advice.horizon == "ready_by"
        assert advice.horizon_ends == "07:00"
