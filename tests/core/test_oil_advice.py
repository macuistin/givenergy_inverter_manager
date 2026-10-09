"""Unit tests for the water heating advice: oil against electricity (core, no Home Assistant).

Figures are chosen to be round. The advice takes the oil's cost per kWh of heat, so the tests
give it directly. The tariff is 0.30 by day and 0.15 from 23:00 to 08:00, with no discount and
no VAT, unless a test says otherwise.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import (
    OIL_BOILER_EFFICIENCY_PCT,
    OIL_KWH_PER_LITRE,
)
from custom_components.givenergy_inverter_manager.core.oil_advice import (
    ALL_DAY,
    SOURCE_ELECTRICITY,
    SOURCE_OIL,
    SOURCE_SOLAR,
    AdviceInputs,
    advise_water_heating,
    oil_heat_cost_per_kwh,
)
from custom_components.givenergy_inverter_manager.core.oil_start import WaterReading
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

DUBLIN = ZoneInfo("Europe/Dublin")
NO_TAX = {"vat_rate": 0, "discount_rate": 0}
TIMED = build_tariff(
    {
        "base_rate": 0.30,
        "export_rate": 0.15,
        "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
        **NO_TAX,
    }
)
FLAT = build_tariff({"base_rate": 0.30, "export_rate": 0.15, "rate_periods": [], **NO_TAX})
NIGHT_BOOST = build_tariff(
    {
        "base_rate": 0.30,
        "export_rate": 0.15,
        "rate_periods": [
            {"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"},
            {"name": "Nightboost", "rate": 0.10, "start": "02:00", "end": "04:00"},
        ],
        **NO_TAX,
    }
)


def at(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 12, day, hour, minute, tzinfo=DUBLIN)


def advise(now: datetime, per_kwh: float, tariff=TIMED, **kwargs):
    return advise_water_heating(AdviceInputs(tariff, now, per_kwh, **kwargs))


class TestOilCost:
    def test_it_is_the_price_over_the_heat_a_litre_gives(self):
        heat_per_litre = OIL_KWH_PER_LITRE * OIL_BOILER_EFFICIENCY_PCT / 100
        assert oil_heat_cost_per_kwh(1.00) == pytest.approx(1.00 / heat_per_litre)

    def test_the_assumptions_are_a_typical_boiler_and_kerosene(self):
        assert OIL_KWH_PER_LITRE == pytest.approx(10.35)
        assert OIL_BOILER_EFFICIENCY_PCT == 85

    def test_a_dearer_litre_costs_more_per_kwh(self):
        assert oil_heat_cost_per_kwh(1.20) > oil_heat_cost_per_kwh(0.90)

    def test_a_negative_price_is_refused(self):
        with pytest.raises(ValueError, match="oil price"):
            oil_heat_cost_per_kwh(-0.1)


class TestElectricityCost:
    def test_the_discount_and_vat_apply_like_the_cost_sensors(self):
        taxed = build_tariff(
            {"base_rate": 0.30, "rate_periods": [], "vat_rate": 10, "discount_rate": 10}
        )
        advice = advise(at(12), 0.20, taxed)
        assert advice.electricity_cost_per_kwh == pytest.approx(0.30 * 0.9 * 1.1)
        assert advice.electricity_cost_per_kwh == pytest.approx(
            taxed.calculate_import_cost(1.0, at(12))
        )

    def test_the_comparison_uses_the_cost_after_tax(self):
        """Oil at 0.28 is cheaper than the 0.30 rate, and dearer than the 0.297 it costs."""
        taxed = build_tariff(
            {"base_rate": 0.30, "rate_periods": [], "vat_rate": 10, "discount_rate": 10}
        )
        assert advise(at(12), 0.29, taxed).source == SOURCE_OIL
        assert advise(at(12), 0.30, taxed).source == SOURCE_ELECTRICITY

    def test_the_cheapest_electricity_is_the_cheapest_rate_in_the_next_day(self):
        assert advise(at(12), 0.20).cheapest_electricity_cost_per_kwh == pytest.approx(0.15)

    def test_the_cheapest_electricity_follows_a_boost_inside_the_night(self):
        assert advise(at(12), 0.20, NIGHT_BOOST).cheapest_electricity_cost_per_kwh == pytest.approx(
            0.10
        )


class TestOilDearerThanEveryRate:
    def test_oil_is_never_suggested(self):
        for hour in range(24):
            advice = advise(at(hour), 0.40)
            assert advice.source == SOURCE_ELECTRICITY, hour
            assert advice.oil_hours == (), hour

    def test_the_sentence_says_electricity_is_cheaper_for_the_day(self):
        advice = advise(at(12), 0.40)
        assert "Electricity is cheaper than oil for the next 24 hours" in advice.suggestion
        assert "immersion" in advice.suggestion

    def test_the_saving_of_oil_is_negative(self):
        assert advise(at(12), 0.40).oil_saving_per_kwh == pytest.approx(0.30 - 0.40)


class TestOilBetweenTheBaseRateAndTheCheapWindow:
    """Oil at 0.20 beats the 0.30 day rate and loses to the 0.15 night rate."""

    def test_in_the_day_oil_is_the_cheapest_source(self):
        advice = advise(at(12), 0.20)
        assert advice.source == SOURCE_OIL
        assert advice.oil_saving_per_kwh == pytest.approx(0.10)

    def test_the_sentence_names_the_end_of_the_oil_hours_and_the_saving(self):
        advice = advise(at(12), 0.20)
        assert advice.suggestion.startswith(
            "Oil is cheaper than electricity until 23:00 (saves about €0.10 per kWh of heat). "
            "Heat the water with the oil system now."
        )

    def test_in_the_cheap_window_electricity_is_the_cheapest_source(self):
        advice = advise(at(1), 0.20)
        assert advice.source == SOURCE_ELECTRICITY
        assert advice.oil_saving_per_kwh == pytest.approx(-0.05)

    def test_the_sentence_in_the_window_says_when_oil_is_cheaper(self):
        advice = advise(at(1), 0.20)
        assert "Electricity is the cheapest source now." in advice.suggestion
        assert "Oil is cheaper than electricity from 08:00 to 23:00" in advice.suggestion

    def test_the_best_hours_for_oil_are_the_day_rate_hours(self):
        assert advise(at(12), 0.20).oil_hours == ("12:00 to 23:00", "08:00 to 12:00")

    def test_asked_in_the_night_the_hours_start_when_the_day_rate_does(self):
        assert advise(at(1), 0.20).oil_hours == ("08:00 to 23:00",)

    def test_the_source_flips_when_the_night_rate_starts(self):
        assert advise(at(22, 59), 0.20).source == SOURCE_OIL
        assert advise(at(23), 0.20).source == SOURCE_ELECTRICITY


class TestWaitingForAnotherWindow:
    def test_oil_now_mentions_a_cheaper_electricity_window_to_come(self):
        advice = advise(at(18), 0.12, NIGHT_BOOST)
        assert advice.source == SOURCE_OIL
        assert "If the water can wait, electricity is cheapest from 02:00 to 04:00" in advice.suggestion

    def test_no_such_sentence_when_oil_beats_every_window(self):
        assert "can wait" not in advise(at(18), 0.05).suggestion

    def test_the_horizon_ends_at_the_ready_time_when_there_is_one(self):
        advice = advise(at(18), 0.12, NIGHT_BOOST, ready_times=(time(7, 0),))
        assert advice.horizon == "ready_by"
        assert advice.horizon_ends == "07:00"
        assert advice.cheapest_source_in_horizon == SOURCE_ELECTRICITY

    def test_the_horizon_is_a_day_without_a_ready_time(self):
        advice = advise(at(18), 0.12, NIGHT_BOOST)
        assert advice.horizon == "next_24_hours"
        assert advice.horizon_ends == "18:00"

    def test_a_ready_time_before_the_cheap_window_leaves_oil_the_cheapest(self):
        advice = advise(at(18), 0.12, NIGHT_BOOST, ready_times=(time(22, 0),))
        assert advice.cheapest_source_in_horizon == SOURCE_OIL
        assert advice.cheapest_electricity_cost_per_kwh == pytest.approx(0.30)
        assert "can wait" not in advice.suggestion

    def test_the_cheapest_electricity_is_looked_for_only_up_to_the_ready_time(self):
        advice = advise(at(18), 0.20, TIMED, ready_times=(time(21, 0),))
        assert advice.cheapest_electricity_cost_per_kwh == pytest.approx(0.30)
        assert advise(at(18), 0.20, TIMED).cheapest_electricity_cost_per_kwh == pytest.approx(0.15)

    def test_the_best_hours_are_still_the_whole_day_with_a_ready_time(self):
        with_ready = advise(at(18), 0.20, ready_times=(time(21, 0),))
        assert with_ready.oil_hours == advise(at(18), 0.20).oil_hours


class TestSolarSurplus:
    def test_solar_is_cheapest_when_the_export_forgone_is_below_oil(self):
        advice = advise(at(12), 0.20, solar_surplus=True)
        assert advice.source == SOURCE_SOLAR
        assert "Solar surplus is the cheapest source now" in advice.suggestion
        assert "0.15" in advice.suggestion
        assert "immersion" in advice.suggestion

    def test_oil_wins_when_the_export_rate_is_above_the_oil_cost(self):
        rich = build_tariff(
            {"base_rate": 0.30, "export_rate": 0.25, "rate_periods": [], **NO_TAX}
        )
        advice = advise(at(12), 0.20, rich, solar_surplus=True)
        assert advice.source == SOURCE_OIL
        assert advice.oil_saving_per_kwh == pytest.approx(0.05)

    def test_the_saving_is_against_the_cheapest_electric_source(self):
        with_surplus = advise(at(12), 0.20, solar_surplus=True)
        assert with_surplus.oil_saving_per_kwh == pytest.approx(0.15 - 0.20)
        assert advise(at(12), 0.20).oil_saving_per_kwh == pytest.approx(0.10)

    def test_with_no_surplus_the_export_rate_is_not_a_source(self):
        assert advise(at(12), 0.20).source == SOURCE_OIL

    def test_free_solar_beats_free_oil(self):
        free_export = build_tariff(
            {"base_rate": 0.30, "export_rate": 0.0, "rate_periods": [], **NO_TAX}
        )
        advice = advise(at(12), 0.0, free_export, solar_surplus=True)
        assert advice.source == SOURCE_SOLAR

    def test_the_hours_for_oil_ignore_solar(self):
        assert advise(at(12), 0.20, solar_surplus=True).oil_hours == advise(at(12), 0.20).oil_hours

    def test_the_day_ahead_counts_solar_as_a_source_when_it_is_there_now(self):
        advice = advise(at(18), 0.20, solar_surplus=True)
        assert advice.cheapest_source_in_horizon == SOURCE_SOLAR


class TestFlatTariff:
    def test_oil_cheaper_than_the_one_rate_is_cheaper_all_day(self):
        advice = advise(at(12), 0.20, FLAT)
        assert advice.source == SOURCE_OIL
        assert advice.oil_hours == (ALL_DAY,)
        assert "for the next 24 hours" in advice.suggestion
        assert "until" not in advice.suggestion

    def test_oil_dearer_than_the_one_rate_is_never_suggested(self):
        advice = advise(at(12), 0.40, FLAT)
        assert advice.source == SOURCE_ELECTRICITY
        assert advice.oil_hours == ()

    def test_the_cheapest_electricity_is_the_one_rate(self):
        assert advise(at(12), 0.20, FLAT).cheapest_electricity_cost_per_kwh == pytest.approx(0.30)


class TestEdges:
    def test_equal_costs_stay_with_electricity(self):
        assert advise(at(12), 0.30).source == SOURCE_ELECTRICITY

    def test_the_saving_is_not_a_money_figure_when_tiny(self):
        advice = advise(at(12), 0.2992)
        assert "saves about €0.001 per kWh" in advice.suggestion

    def test_the_currency_symbol_leads_each_figure(self):
        advice = advise(at(12), 0.20, currency_symbol="£")
        assert "£0.10 per kWh" in advice.suggestion

    def test_the_hours_run_across_midnight_in_order(self):
        reverse = build_tariff(
            {
                "base_rate": 0.10,
                "rate_periods": [{"name": "Peak", "rate": 0.40, "start": "17:00", "end": "20:00"}],
                **NO_TAX,
            }
        )
        advice = advise(at(21), 0.20, reverse)
        assert advice.oil_hours == ("17:00 to 20:00",)
        assert advice.source == SOURCE_ELECTRICITY

    def test_a_peak_after_now_gives_oil_hours_that_start_later(self):
        peak = build_tariff(
            {
                "base_rate": 0.10,
                "rate_periods": [{"name": "Peak", "rate": 0.40, "start": "17:00", "end": "20:00"}],
                **NO_TAX,
            }
        )
        advice = advise(at(12), 0.20, peak)
        assert advice.oil_hours == ("17:00 to 20:00",)
        assert "Oil is cheaper than electricity from 17:00 to 20:00" in advice.suggestion

    def test_a_day_ahead_that_gains_an_hour_still_ends_at_the_same_clock_time(self):
        """The clocks go back in the small hours of 25 October, so the next 24 hours end at 11:00."""
        before_change = datetime(2026, 10, 24, 12, 0, tzinfo=DUBLIN)
        advice = advise(before_change, 0.20)
        assert advice.oil_hours == ("12:00 to 23:00", "08:00 to 11:00")


# -- the water, the ready-by oil start and the keep-warm run --

READY = {"ready_times": (time(19, 0),), "scheduled_heating": True}
AT_TARGET = "The water is already at the target, so there is nothing to heat."


def water(temp: float = 40.0, min_temp: float = 30.0, gap: float = 5.0) -> WaterReading:
    """Heats at 10 degrees an hour to 55, so 15 degrees is 1.725 hours with the margin: 104 minutes.

    The minimum is low by default, so the keep-warm run stays out of the way of the other tests.
    """
    return WaterReading(temp, 55.0, 10.0, min_temp, gap)


class TestTheOilStartSentence:
    def test_cold_water_and_cheaper_oil_say_when_to_start(self):
        advice = advise(at(15), 0.20, water=water(), **READY)
        assert advice.suggestion == (
            "For the 19:00 ready time: turn the oil water heating on at 15:32 (about 104 minutes). "
            "The immersion will only top up. Saves about €0.10 per kWh of heat."
        )

    def test_the_start_and_the_ready_time_are_in_the_data(self):
        start = advise(at(15), 0.20, water=water(), **READY).oil_start
        assert (start.start_by, start.run_minutes, start.ready_at) == (at(15, 32), 104, at(19))

    def test_the_source_and_the_other_figures_are_what_they_were(self):
        with_water = advise(at(15), 0.20, water=water(), **READY)
        without = advise(at(15), 0.20, **READY)
        assert with_water.source == without.source == SOURCE_OIL
        assert with_water.oil_hours == without.oil_hours
        assert with_water.oil_saving_per_kwh == without.oil_saving_per_kwh

    def test_a_flat_tariff_suggests_a_start_too(self):
        advice = advise(at(15), 0.20, FLAT, water=water(), **READY)
        assert "turn the oil water heating on at 15:32" in advice.suggestion

    def test_a_start_the_next_day_says_so(self):
        advice = advise(at(22), 0.20, FLAT, water=water(), ready_times=(time(7),), scheduled_heating=True)
        assert advice.suggestion.startswith(
            "For tomorrow's 07:00 ready time: turn the oil water heating on at 03:32 tomorrow "
        )

    def test_too_late_for_the_oil_alone_says_now_and_that_the_immersion_will_share(self):
        advice = advise(at(17), 0.20, water=water(), **READY)
        assert advice.suggestion == (
            "For the 19:00 ready time: turn the oil water heating on now (about 104 minutes). "
            "It is too late for the oil to finish before the immersion has to start, so the "
            "immersion will also run. Saves up to €0.10 per kWh of heat."
        )

    def test_two_ready_times_give_the_next_one(self):
        both = {"ready_times": (time(7), time(19)), "scheduled_heating": True}
        assert advise(at(8), 0.20, FLAT, water=water(), **both).oil_start.ready_at == at(19)
        assert advise(at(20), 0.20, FLAT, water=water(), **both).oil_start.ready_at == at(
            7, day=16
        )

    def test_scheduled_heating_off_means_no_immersion_to_top_up_so_no_start(self):
        advice = advise(at(15), 0.20, water=water(), ready_times=(time(19),))
        assert advice.oil_start is None
        assert advice.suggestion.endswith("Heat the water with the oil system now.")

    def test_no_ready_time_means_no_start(self):
        advice = advise(at(15), 0.20, water=water(), scheduled_heating=True)
        assert advice.oil_start is None

    def test_no_water_reading_leaves_the_sentence_as_it_was(self):
        advice = advise(at(15), 0.20, **READY)
        assert advice.oil_start is None
        assert advice.suggestion.endswith("Heat the water with the oil system now.")


class TestNoStartForATrivialTopUp:
    """The water is above the temperature at which the immersion restarts: there is nothing to start."""

    def test_water_at_54_point_4_says_no_heating_is_needed_and_not_a_start(self):
        advice = advise(at(15), 0.20, water=water(temp=54.4, gap=4.0), **READY)
        assert advice.oil_start is None
        assert advice.suggestion == (
            "For the 19:00 ready time: the water is expected to be ready with no heating needed."
        )

    def test_the_sentence_names_tomorrows_ready_time(self):
        advice = advise(
            at(22), 0.20, water=water(temp=54.4, gap=4.0), ready_times=(time(7),), scheduled_heating=True
        )
        assert advice.suggestion == (
            "For tomorrow's 07:00 ready time: the water is expected to be ready with no heating "
            "needed."
        )

    def test_cold_water_still_gets_a_start(self):
        advice = advise(at(15), 0.20, water=water(temp=40.0, gap=4.0), **READY)
        assert advice.oil_start.start_by == at(15, 32)
        assert "turn the oil water heating on at 15:32" in advice.suggestion

    def test_water_just_below_the_restart_threshold_gets_a_start(self):
        advice = advise(at(15), 0.20, water=water(temp=50.9, gap=4.0), **READY)
        assert advice.oil_start.start_by is not None

    def test_water_at_the_restart_threshold_gets_none(self):
        advice = advise(at(15), 0.20, water=water(temp=51.0, gap=4.0), **READY)
        assert advice.oil_start is None
        assert "no heating needed" in advice.suggestion

    def test_without_scheduled_heating_the_sentence_is_the_plain_one(self):
        advice = advise(at(15), 0.20, water=water(temp=54.4, gap=4.0), ready_times=(time(19),))
        assert "no heating needed" not in advice.suggestion
        assert advice.suggestion.endswith("Heat the water with the oil system now.")

    def test_water_at_the_target_keeps_its_own_sentence(self):
        advice = advise(at(15), 0.20, water=water(temp=55.0, gap=4.0), **READY)
        assert advice.suggestion.endswith(AT_TARGET)


class TestNoOilStartNeeded:
    def test_electricity_in_the_cheap_slot_beats_oil_for_the_morning(self):
        advice = advise(at(1), 0.20, water=water(), ready_times=(time(7),), scheduled_heating=True)
        assert advice.oil_start.start_by is None
        assert advice.suggestion == (
            "For the 07:00 ready time: electricity is cheaper than oil, so the immersion will "
            "heat the water."
        )

    def test_the_night_band_before_a_morning_ready_time_beats_oil_even_when_oil_is_cheaper_now(self):
        advice = advise(at(15), 0.20, water=water(), ready_times=(time(7),), scheduled_heating=True)
        assert advice.source == SOURCE_OIL
        assert "For tomorrow's 07:00 ready time: electricity is cheaper than oil" in advice.suggestion

    def test_solar_surplus_cheaper_than_oil_leaves_it_to_the_immersion(self):
        advice = advise(at(15), 0.20, water=water(), solar_surplus=True, **READY)
        assert advice.source == SOURCE_SOLAR
        assert advice.suggestion == (
            "For the 19:00 ready time: solar surplus is cheaper than oil, so the immersion will "
            "heat the water."
        )

    def test_water_already_at_the_target_says_there_is_nothing_to_heat(self):
        advice = advise(at(15), 0.20, water=water(temp=55.0), **READY)
        assert advice.oil_start is None
        assert advice.suggestion == (
            "Oil is cheaper than electricity until 23:00 (saves about €0.10 per kWh of heat). "
            + AT_TARGET
        )

    def test_the_wait_for_cheaper_electricity_is_dropped_when_there_is_nothing_to_heat(self):
        advice = advise(at(18), 0.12, NIGHT_BOOST, water=water(temp=56.0))
        assert "can wait" not in advice.suggestion
        assert advice.suggestion.endswith(AT_TARGET)

    def test_the_solar_and_electricity_sentences_say_so_too(self):
        solar = advise(at(12), 0.20, water=water(temp=55.0), solar_surplus=True)
        assert solar.suggestion.endswith(AT_TARGET)
        electricity = advise(at(12), 0.40, water=water(temp=55.0))
        assert electricity.suggestion.endswith(AT_TARGET)
        assert "Heat the water" not in electricity.suggestion

    def test_cold_water_with_no_ready_times_keeps_the_old_sentence(self):
        advice = advise(at(12), 0.20, water=water())
        assert advice.suggestion == advise(at(12), 0.20).suggestion


class TestKeepWarm:
    COLD_ISH = water(temp=49.5, min_temp=45.0)
    TEXT = (
        "Water is at 49.5°C, close to the 45°C minimum. Oil is cheaper than the grid now "
        "(€0.16 against €0.30 per kWh of heat): run the oil water heating for about 40 minutes "
        "to avoid an electric top-up."
    )

    def test_water_above_the_minimum_plus_the_gap_gets_none(self):
        advice = advise(at(12), 0.16, water=water(temp=50.5, min_temp=45.0))
        assert advice.keep_warm is None

    def test_water_at_the_threshold_with_cheaper_oil_gets_a_run(self):
        advice = advise(at(12), 0.16, water=water(temp=50.0, min_temp=45.0))
        assert advice.keep_warm is not None

    def test_below_the_threshold_with_cheaper_oil_says_why_and_for_how_long(self):
        advice = advise(at(12), 0.16, water=self.COLD_ISH)
        assert advice.keep_warm == self.TEXT
        assert advice.suggestion == self.TEXT

    def test_inside_the_cheap_slot_oil_is_not_cheaper_than_the_grid_so_none(self):
        advice = advise(at(1), 0.20, water=self.COLD_ISH)
        assert advice.keep_warm is None
        assert "run the oil" not in advice.suggestion

    def test_solar_surplus_already_heating_gives_none(self):
        advice = advise(at(12), 0.10, water=self.COLD_ISH, solar_surplus=True)
        assert advice.keep_warm is None

    def test_it_works_without_scheduled_heating_or_ready_times(self):
        assert advise(at(12), 0.16, water=self.COLD_ISH).keep_warm == self.TEXT

    def test_without_a_water_reading_there_is_none(self):
        assert advise(at(12), 0.16).keep_warm is None

    def test_the_ready_by_start_comes_first_when_both_apply(self):
        advice = advise(at(15), 0.16, water=self.COLD_ISH, **READY)
        assert advice.suggestion.startswith("For the 19:00 ready time: turn the oil water heating on at")
        assert advice.keep_warm == self.TEXT

    def test_keep_warm_comes_before_electricity_being_cheaper_for_the_ready_time(self):
        advice = advise(
            at(15), 0.16, water=self.COLD_ISH, ready_times=(time(7),), scheduled_heating=True
        )
        assert advice.oil_start.start_by is None
        assert advice.suggestion == self.TEXT
