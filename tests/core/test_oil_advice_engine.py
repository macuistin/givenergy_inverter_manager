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


READY_AT_19 = {
    "immersion_temp": 40.0,
    "immersion_heating_rate_c_per_h": 10.0,
    "immersion_min_temp": 30.0,
    "immersion_ready_times": (time(19, 0),),
    "immersion_schedule_enabled": True,
}


def cycle(hour: int, minute: int = 0, **raw):
    fields = {"solar_power_w": 0.0, "house_load_w": 400.0, "battery_soc": 20.0, **raw}
    return _run(raw=_raw(**fields), cfg=CFG, now=datetime(2026, 12, 15, hour, minute))[0]


class TestTheOilStart:
    def test_cold_water_and_cheaper_oil_get_a_start_for_the_next_ready_time(self):
        advice = cycle(15, oil_price_per_litre=price_for(0.20), **READY_AT_19).water_heating_advice
        assert advice.oil_start.start_by == datetime(2026, 12, 15, 15, 32)
        assert advice.suggestion.startswith(
            "For the 19:00 ready time: turn the oil water heating on at 15:32 (about 104 minutes)."
        )

    def test_the_immersion_decision_is_the_same_with_and_without_an_oil_price(self):
        for hour, minute in ((15, 0), (17, 17), (18, 30)):
            without = cycle(hour, minute, **READY_AT_19)
            with_oil = cycle(hour, minute, oil_price_per_litre=price_for(0.20), **READY_AT_19)
            assert with_oil.should_divert_immersion == without.should_divert_immersion
            assert with_oil.divert_reason == without.divert_reason

    def test_the_immersion_is_the_backstop_so_it_starts_after_the_suggested_oil_would_finish(self):
        assert cycle(15, **READY_AT_19).should_divert_immersion is False
        assert cycle(17, 17, **READY_AT_19).should_divert_immersion is True

    def test_scheduled_heating_off_gives_no_start(self):
        raw = {**READY_AT_19, "immersion_schedule_enabled": False}
        advice = cycle(15, oil_price_per_litre=price_for(0.20), **raw).water_heating_advice
        assert advice.oil_start is None

    def test_no_temperature_reading_gives_no_start_and_the_old_sentence(self):
        raw = {**READY_AT_19, "immersion_temp": None}
        advice = cycle(15, oil_price_per_litre=price_for(0.20), **raw).water_heating_advice
        assert advice.oil_start is None
        assert advice.suggestion.endswith("Heat the water with the oil system now.")

    def test_water_at_the_target_gets_no_start_and_says_so(self):
        raw = {**READY_AT_19, "immersion_temp": 56.0}
        advice = cycle(15, oil_price_per_litre=price_for(0.20), **raw).water_heating_advice
        assert advice.oil_start is None
        assert advice.suggestion.endswith("so there is nothing to heat.")

    def test_electricity_cheaper_for_the_ready_time_gives_no_start(self):
        raw = {**READY_AT_19, "immersion_ready_times": (time(7, 0),)}
        advice = cycle(1, oil_price_per_litre=price_for(0.20), **raw).water_heating_advice
        assert advice.oil_start.start_by is None

    def test_no_oil_price_gives_no_advice_at_all(self):
        assert cycle(15, **READY_AT_19).water_heating_advice is None


class TestKeepWarm:
    COOLING = {"immersion_temp": 49.5, "immersion_heating_rate_c_per_h": 10.0, "immersion_min_temp": 45.0}

    def test_cooling_water_with_cheaper_oil_gets_a_run(self):
        advice = cycle(12, oil_price_per_litre=price_for(0.16), **self.COOLING).water_heating_advice
        assert advice.keep_warm.endswith("for about 40 minutes to avoid an electric top-up.")

    def test_it_uses_the_configured_minimum_and_restart_gap(self):
        raw = {**self.COOLING, "immersion_min_temp": 40.0, "immersion_hysteresis_c": 5.0}
        assert cycle(12, oil_price_per_litre=price_for(0.16), **raw).water_heating_advice.keep_warm is None

    def test_in_the_cheap_slot_it_does_not_apply(self):
        advice = cycle(1, oil_price_per_litre=price_for(0.16), **self.COOLING).water_heating_advice
        assert advice.keep_warm is None

    def test_no_oil_price_gives_nothing(self):
        assert cycle(12, **self.COOLING).water_heating_advice is None
