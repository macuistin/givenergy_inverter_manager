"""The advice sentences call the alternative heating by the user's label.

Every sentence path is run with a gas, a heat pump and an all-capitals label, and with a label
that is empty or far too long. The default label, Oil, gives the sentences the oil advice always
had: test_alt_heat_advice.py pins them word for word.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import ALT_HEAT_LABEL_MAX_LENGTH
from custom_components.givenergy_inverter_manager.core.alt_heat_advice import (
    AdviceInputs,
    advise_water_heating,
)
from custom_components.givenergy_inverter_manager.core.alt_heat_start import WaterReading
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
READY = {"ready_times": (time(19, 0),), "scheduled_heating": True}


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 15, hour, minute, tzinfo=DUBLIN)


def advise(label, now, cost, tariff=TIMED, **kwargs):
    return advise_water_heating(AdviceInputs(tariff, now, cost, label=label, **kwargs))


def water(temp: float = 40.0, min_temp: float = 30.0) -> WaterReading:
    return WaterReading(temp, 55.0, 10.0, min_temp, 5.0)


class TestEachSentence:
    def test_the_cheaper_than_electricity_sentence(self):
        text = advise("Gas", at(12), 0.20).suggestion
        assert text == (
            "Gas is cheaper than electricity until 23:00 (saves about €0.10 per kWh of heat). "
            "Heat the water with the gas system now. If the water can wait, electricity is "
            "cheapest from 23:00 to 08:00 (€0.15 per kWh of heat)."
        )

    def test_a_label_of_two_words_reads_as_two_words(self):
        text = advise("Heat pump", at(12), 0.20).suggestion
        assert text.startswith("Heat pump is cheaper than electricity until 23:00")
        assert "Heat the water with the heat pump system now." in text

    def test_a_label_in_capitals_stays_in_capitals(self):
        text = advise("LPG", at(12), 0.20).suggestion
        assert text.startswith("LPG is cheaper than electricity")
        assert "Heat the water with the LPG system now." in text

    def test_electricity_cheaper_for_the_whole_day(self):
        text = advise("Gas", at(12), 0.40).suggestion
        assert text.startswith("Electricity is cheaper than gas for the next 24 hours.")

    def test_electricity_cheapest_now_and_the_alternative_cheaper_later(self):
        text = advise("Gas", at(1), 0.20).suggestion
        assert "Gas is cheaper than electricity from 08:00 to 23:00" in text

    def test_the_start_for_a_ready_time(self):
        text = advise("Gas", at(15), 0.20, water=water(), **READY).suggestion
        assert text == (
            "For the 19:00 ready time: turn the gas water heating on at 15:32 (about 104 minutes). "
            "The immersion will only top up. Saves about €0.10 per kWh of heat."
        )

    def test_a_start_that_is_too_late(self):
        text = advise("Heat pump", at(17), 0.20, water=water(), **READY).suggestion
        assert text == (
            "For the 19:00 ready time: turn the heat pump water heating on now (about 104 "
            "minutes). It is too late for the heat pump to finish before the immersion has to "
            "start, so the immersion will also run. Saves up to €0.10 per kWh of heat."
        )

    def test_electricity_cheaper_than_the_alternative_for_the_ready_time(self):
        text = advise(
            "Gas", at(1), 0.20, water=water(), ready_times=(time(7),), scheduled_heating=True
        ).suggestion
        assert text == (
            "For the 07:00 ready time: electricity is cheaper than gas, so the immersion will "
            "heat the water."
        )

    def test_the_keep_warm_run(self):
        text = advise("Gas", at(12), 0.16, water=water(temp=49.5, min_temp=45.0)).suggestion
        assert text == (
            "Water is at 49.5°C, close to the 45°C minimum. Gas is cheaper than the grid now "
            "(€0.16 against €0.30 per kWh of heat): run the gas water heating for about 40 "
            "minutes to avoid an electric top-up."
        )

    def test_the_wait_for_cheaper_electricity(self):
        text = advise("Gas", at(18), 0.12, NIGHT_BOOST).suggestion
        assert "If the water can wait, electricity is cheapest from 02:00 to 04:00" in text


class TestTheDefaultLabel:
    def test_oil_is_the_default(self):
        advice = advise_water_heating(AdviceInputs(TIMED, at(12), 0.20))
        assert advice.label == "Oil"
        assert advice.suggestion.startswith("Oil is cheaper than electricity until 23:00")

    def test_an_explicit_oil_matches_the_default(self):
        assert advise("Oil", at(12), 0.20) == advise_water_heating(
            AdviceInputs(TIMED, at(12), 0.20)
        )

    def test_a_lower_case_oil_reads_the_same(self):
        assert advise("oil", at(12), 0.20).suggestion == advise("Oil", at(12), 0.20).suggestion


class TestAnOddLabel:
    @pytest.mark.parametrize("label", ["", "   ", None])
    def test_an_empty_label_says_oil(self, label):
        advice = advise(label, at(12), 0.20)
        assert advice.label == "Oil"
        assert advice.suggestion.startswith("Oil is cheaper than electricity")

    def test_a_very_long_label_is_cut_in_every_sentence(self):
        label = "Biomass boiler with a very long name " * 30
        shown = label[:ALT_HEAT_LABEL_MAX_LENGTH].rstrip()
        for advice in (
            advise(label, at(12), 0.20),
            advise(label, at(12), 0.40),
            advise(label, at(15), 0.20, water=water(), **READY),
            advise(label, at(12), 0.16, water=water(temp=49.5, min_temp=45.0)),
        ):
            assert advice.label == shown
            assert label[: ALT_HEAT_LABEL_MAX_LENGTH + 1] not in advice.suggestion
            assert len(advice.suggestion) < 400

    def test_a_label_with_a_line_break_stays_on_one_line(self):
        advice = advise("Gas\nboiler", at(12), 0.20)
        assert "\n" not in advice.suggestion
        assert "gas boiler system" in advice.suggestion

    def test_text_that_looks_like_a_format_field_is_kept_as_it_is(self):
        advice = advise("{saving}", at(12), 0.20)
        assert advice.suggestion.startswith("{saving} is cheaper than electricity")
