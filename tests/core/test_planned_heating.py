"""Unit tests for the planned heating sentence (core, no Home Assistant).

The tariff is 0.30 by day and 0.15 from 23:00 to 08:00. NIGHT_BOOST adds a 0.10 slot from 02:00
to 04:00, which is then the cheapest window. The water is lifted at 10 degrees an hour to 55,
so 15 degrees takes 1.5 hours and the margin makes it 1.725 hours. The restart gap is 4, so the
immersion restarts below 51.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.immersion_ready import (
    ReadyInputs,
    plan_ready,
)
from custom_components.givenergy_inverter_manager.core.immersion_window import (
    next_window_opening,
)
from custom_components.givenergy_inverter_manager.core.oil_start import WaterReading
from custom_components.givenergy_inverter_manager.core.planned_heating import (
    PlanQuery,
    describe_planned_heating,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

DUBLIN = ZoneInfo("Europe/Dublin")
NO_TAX = {"vat_rate": 0, "discount_rate": 0}
NIGHT = {"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}
BOOST = {"name": "Nightboost", "rate": 0.10, "start": "02:00", "end": "04:00"}


def tariff(*periods: dict):
    return build_tariff(
        {
            "base_rate": 0.30,
            "base_rate_name": "Day",
            "export_rate": 0.15,
            "rate_periods": list(periods),
            **NO_TAX,
        }
    )


FLAT, TIMED, NIGHT_BOOST = tariff(), tariff(NIGHT), tariff(NIGHT, BOOST)
EVENING, MORNING = (time(19, 0),), (time(7, 0),)


def at(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 12, day, hour, minute, tzinfo=DUBLIN)


def water(temp: float = 40.0) -> WaterReading:
    return WaterReading(temp, 55.0, 10.0, 30.0, 4.0)


def describe(now, tariff_=TIMED, times=EVENING, temp=40.0, heater_on=False) -> str:
    return describe_planned_heating(PlanQuery(tariff_, now, times, water(temp), heater_on))


class TestWaterAlreadyReady:
    def test_no_heating_is_planned_and_the_next_window_is_named(self):
        text = describe(at(1), NIGHT_BOOST, EVENING, temp=54.4)
        assert text == (
            "No heating planned for the 19:00 ready time (water 54.4°C, ready). "
            "Next possible heating: 02:00 to 04:00 slot, only if the water is below 51°C by then."
        )

    def test_a_window_that_opens_tomorrow_says_so(self):
        text = describe(at(15), NIGHT_BOOST, EVENING, temp=54.4)
        assert text.endswith(
            "Next possible heating: 02:00 to 04:00 slot tomorrow, only if the water is below "
            "51°C by then."
        )

    def test_water_at_the_target_is_ready_too(self):
        assert describe(at(15), TIMED, EVENING, temp=55.0).startswith(
            "No heating planned for the 19:00 ready time (water 55.0°C, ready)."
        )

    def test_water_at_the_restart_threshold_is_ready(self):
        assert "(water 51.0°C, ready)" in describe(at(15), TIMED, EVENING, temp=51.0)

    def test_a_ready_time_tomorrow_says_so(self):
        text = describe(at(22), TIMED, MORNING, temp=54.4)
        assert text.startswith("No heating planned for tomorrow's 07:00 ready time (water 54.4°C")

    def test_a_flat_tariff_has_no_window_to_name(self):
        assert describe(at(15), FLAT, EVENING, temp=54.4) == (
            "No heating planned for the 19:00 ready time (water 54.4°C, ready)."
        )

    def test_the_window_open_now_is_named_as_open(self):
        text = describe(at(23, 30), TIMED, EVENING, temp=54.4)
        assert text.endswith(
            "The 23:00 to 08:00 slot is open now, heating only if the water is below 51°C."
        )


class TestColdWaterWithAPlan:
    def test_the_start_and_end_and_the_rate_band_are_named(self):
        """The plan starts at 17:16:30, 1.725 hours before 19:00, in the day band."""
        assert describe(at(15)) == (
            "Heating planned for the 19:00 ready time: 17:16 to 19:00 at the Day rate."
        )

    def test_the_cheap_slot_is_used_when_it_comes_before_the_ready_time(self):
        text = describe(at(22), NIGHT_BOOST, MORNING)
        assert text == (
            "Heating planned for tomorrow's 07:00 ready time: 02:16 to 04:00 tomorrow "
            "at the Nightboost rate."
        )

    def test_heating_in_two_bands_lists_both_in_time_order(self):
        text = describe(at(22), NIGHT_BOOST, MORNING, temp=30.0)
        assert text == (
            "Heating planned for tomorrow's 07:00 ready time: 02:00 to 04:00 tomorrow at the "
            "Nightboost rate and 06:07 to 07:00 tomorrow at the Night rate."
        )

    def test_the_plan_matches_the_one_the_immersion_follows(self):
        ready = plan_ready(ReadyInputs(TIMED, at(17, 15), EVENING, 40.0, 55.0, 10.0))
        later = plan_ready(ReadyInputs(TIMED, at(17, 17), EVENING, 40.0, 55.0, 10.0))
        assert (ready.heat_now, later.heat_now) == (False, True)
        assert describe(at(17, 15)).startswith("Heating planned for the 19:00 ready time: 17:16")
        assert describe(at(17, 17)).startswith("Heating now")

    def test_the_planning_leaves_the_immersion_plan_unchanged(self):
        inputs = ReadyInputs(TIMED, at(15), EVENING, 40.0, 55.0, 10.0)
        before = plan_ready(inputs)
        describe(at(15))
        assert plan_ready(inputs) == before


class TestHeatingNow:
    def test_it_says_now_and_when_the_heating_ends(self):
        assert describe(at(17, 51), TIMED, EVENING, temp=45.0) == (
            "Heating now to be ready by 19:00 (water 45.0°C, target 55°C): "
            "until 19:00 at the Day rate."
        )

    def test_water_that_cannot_be_ready_in_time_says_so(self):
        text = describe(at(18, 30))
        assert text.startswith("Heating now to be ready by 19:00 (water 40.0°C, target 55°C)")
        assert text.endswith("The water will not be fully ready by then.")

    def test_a_run_in_progress_carries_on(self):
        """Heater on, the plan would start within the switch cooldown: it carries on."""
        text = describe(at(17, 10), TIMED, EVENING, temp=40.0, heater_on=True)
        assert text.startswith("Heating now to be ready by 19:00")
        assert text.endswith("until 19:00 at the Day rate.")

    def test_the_cheap_window_heating_now_is_named(self):
        text = describe(at(23, 30), TIMED, (), temp=40.0)
        assert text == "Heating now in the Night slot until 08:00 tomorrow (water 40.0°C, target 55°C)."

    def test_a_heater_that_is_on_carries_on_to_the_target_in_the_window(self):
        text = describe(at(23, 30), TIMED, (), temp=54.0, heater_on=True)
        assert text.startswith("Heating now in the Night slot")


class TestNoReadyTimes:
    def test_only_the_cheap_window_is_described(self):
        assert describe(at(15), NIGHT_BOOST, ()) == (
            "No ready time is set. Next possible heating: 02:00 to 04:00 slot tomorrow, only if "
            "the water is below 51°C by then."
        )

    def test_a_flat_tariff_has_nothing_planned(self):
        assert describe(at(15), FLAT, ()) == (
            "No heating planned: no ready time is set and the tariff has no cheaper slot."
        )

    def test_a_window_dearer_than_the_base_rate_is_no_window(self):
        dear = tariff({"name": "Peak", "rate": 0.40, "start": "17:00", "end": "20:00"})
        assert describe(at(15), dear, ()).startswith("No heating planned: no ready time is set")


class TestNextWindowOpening:
    def test_a_closed_window_gives_its_next_start_and_end(self):
        opening = next_window_opening(NIGHT_BOOST, at(1))
        assert (opening.name, opening.start, opening.end, opening.is_open) == (
            "Nightboost",
            at(2),
            at(4),
            False,
        )

    def test_after_the_window_it_is_tomorrows(self):
        opening = next_window_opening(NIGHT_BOOST, at(15))
        assert (opening.start, opening.end) == (at(2, day=16), at(4, day=16))

    def test_an_open_window_gives_the_start_it_opened_at(self):
        opening = next_window_opening(TIMED, at(1))
        assert (opening.start, opening.end, opening.is_open) == (at(23, day=14), at(8), True)

    def test_a_window_open_before_midnight_ends_tomorrow(self):
        opening = next_window_opening(TIMED, at(23, 30))
        assert (opening.start, opening.end) == (at(23), at(8, day=16))

    def test_a_flat_tariff_has_none(self):
        assert next_window_opening(FLAT, at(1)) is None

    def test_a_window_dearer_than_the_base_rate_is_none(self):
        dear = tariff({"name": "Peak", "rate": 0.40, "start": "17:00", "end": "20:00"})
        assert next_window_opening(dear, at(1)) is None


@pytest.mark.parametrize("temp", [54.4, 40.0])
def test_the_sentence_never_uses_an_em_dash(temp):
    assert "—" not in describe(at(1), NIGHT_BOOST, EVENING, temp=temp)
