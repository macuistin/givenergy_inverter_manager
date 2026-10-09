"""Unit tests for the oil start time and the keep-warm run (core, no Home Assistant).

The tariff is 0.30 by day and 0.15 from 23:00 to 08:00, with no discount and no VAT. The
water is lifted at 10 degrees an hour, so 15 degrees takes 1.5 hours and the margin makes it
1.725 hours, which is 104 minutes rounded up.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import CHARGE_WINDOW_MARGIN
from custom_components.givenergy_inverter_manager.core.immersion_ready import (
    ReadyInputs,
    plan_ready,
)
from custom_components.givenergy_inverter_manager.core.oil_start import (
    StartQuery,
    WaterReading,
    keep_warm_minutes,
    suggest_oil_start,
)
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
TARGET, RATE = 55.0, 10.0
RUN_MINUTES = math.ceil((TARGET - 40.0) / RATE * (1 + CHARGE_WINDOW_MARGIN) * 60)


def at(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 12, day, hour, minute, tzinfo=DUBLIN)


def water(temp: float = 40.0, min_temp: float = 45.0, gap: float = 5.0) -> WaterReading:
    return WaterReading(temp, TARGET, RATE, min_temp, gap)


def suggest(now, ready, tariff=TIMED, oil=0.20, solar=None, reading=None):
    query = StartQuery(tariff, now, reading or water(), oil, solar)
    return suggest_oil_start(query, ready)


class TestTheOilStart:
    def test_oil_cheaper_and_water_cold_starts_the_oil_early_enough(self):
        """The immersion would start at 17:16:30 (103.5 minutes before 19:00). Oil takes 104."""
        result = suggest(at(15), at(19))
        assert result.run_minutes == RUN_MINUTES == 104
        assert result.start_by == at(15, 32)
        assert result.late is False
        assert result.saving_per_kwh == pytest.approx(0.10)

    def test_the_oil_finishes_before_the_immersion_would_have_to_start(self):
        result = suggest(at(15), at(19))
        ready = (at(19).timetz().replace(tzinfo=None),)
        assert plan_ready(ReadyInputs(TIMED, at(17, 15), ready, 40.0, TARGET, RATE)).heat_now is False
        assert plan_ready(ReadyInputs(TIMED, at(17, 17), ready, 40.0, TARGET, RATE)).heat_now is True
        assert result.start_by + timedelta(minutes=result.run_minutes) <= at(17, 17)

    def test_the_immersion_plan_is_not_changed_by_the_suggestion(self):
        ready = (at(19).timetz().replace(tzinfo=None),)
        before = plan_ready(ReadyInputs(TIMED, at(15), ready, 40.0, TARGET, RATE))
        suggest(at(15), at(19))
        assert plan_ready(ReadyInputs(TIMED, at(15), ready, 40.0, TARGET, RATE)) == before
        assert before.heat_now is False

    def test_the_start_is_rounded_down_to_the_minute(self):
        assert suggest(at(15), at(19)).start_by.second == 0

    def test_a_flat_tariff_suggests_a_start_too(self):
        result = suggest(at(15), at(19), FLAT)
        assert result.start_by == at(15, 32)
        assert result.saving_per_kwh == pytest.approx(0.10)

    def test_a_ready_time_tomorrow_gives_a_start_tomorrow(self):
        assert suggest(at(22), at(7, day=16), FLAT).start_by == at(3, 32, day=16)

    def test_too_late_to_finish_before_the_immersion_starts_means_start_now(self):
        result = suggest(at(17), at(19))
        assert result.late is True
        assert result.start_by == at(17)

    def test_the_start_never_goes_before_now(self):
        assert suggest(at(15, 40), at(19)).start_by >= at(15, 40)

    def test_water_at_the_target_needs_no_start(self):
        assert suggest(at(15), at(19), reading=water(temp=55.0)) is None
        assert suggest(at(15), at(19), reading=water(temp=60.0)) is None


class TestWhenOilIsNotTheCheaperHeat:
    def test_electricity_in_the_cheap_slot_beats_oil(self):
        """Ready at 07:00 from 01:00: the plan sits in the night rate of 0.15."""
        result = suggest(at(1), at(7))
        assert result.start_by is None
        assert result.by_solar is False
        assert result.electric_cost_per_kwh == pytest.approx(0.15)

    def test_the_cheap_slot_before_a_morning_ready_time_beats_oil_from_the_afternoon_too(self):
        result = suggest(at(15), at(7, day=16))
        assert result.start_by is None

    def test_a_mixed_plan_is_judged_by_its_average_rate(self):
        """Ready at 23:30 from 21:00: 0.5 of the 1.725 hours fall in the night rate."""
        result = suggest(at(21), at(23, 30))
        assert result.electric_cost_per_kwh == pytest.approx((0.5 * 0.15 + 1.225 * 0.30) / 1.725)
        assert result.start_by is not None

    def test_oil_dearer_than_every_rate_is_never_suggested(self):
        assert suggest(at(15), at(19), oil=0.40).start_by is None

    def test_equal_costs_stay_with_electricity(self):
        assert suggest(at(15), at(19), oil=0.30).start_by is None

    def test_solar_surplus_cheaper_than_oil_leaves_the_heating_to_the_immersion(self):
        result = suggest(at(15), at(19), solar=0.15)
        assert result.start_by is None
        assert result.by_solar is True
        assert result.electric_cost_per_kwh == pytest.approx(0.15)

    def test_solar_surplus_dearer_than_oil_does_not_stop_the_start(self):
        result = suggest(at(15), at(19), oil=0.10, solar=0.15)
        assert result.start_by is not None
        assert result.saving_per_kwh == pytest.approx(0.05)

    def test_the_cost_comes_after_discount_and_vat(self):
        taxed = build_tariff({"base_rate": 0.30, "rate_periods": [], "vat_rate": 10, "discount_rate": 10})
        assert suggest(at(15), at(19), taxed, oil=0.29).start_by is not None
        assert suggest(at(15), at(19), taxed, oil=0.30).start_by is None


class TestKeepWarm:
    def test_it_is_the_minutes_to_the_target_rounded_up_to_five(self):
        # 49.5 to 55 at 10 an hour is 0.55 hours, 0.6325 with the margin, 38 minutes, so 40.
        assert keep_warm_minutes(water(temp=49.5), 0.38, 0.16) == 40

    def test_at_the_threshold_it_applies(self):
        assert keep_warm_minutes(water(temp=50.0), 0.38, 0.16) is not None

    def test_above_the_threshold_it_does_not(self):
        assert keep_warm_minutes(water(temp=50.1), 0.38, 0.16) is None

    def test_the_threshold_is_the_minimum_plus_the_restart_gap(self):
        assert keep_warm_minutes(water(temp=52.0, min_temp=47.0, gap=5.0), 0.38, 0.16) is not None
        assert keep_warm_minutes(water(temp=52.1, min_temp=47.0, gap=5.0), 0.38, 0.16) is None

    def test_oil_that_is_not_cheaper_than_the_grid_now_gives_nothing(self):
        assert keep_warm_minutes(water(temp=48.0), 0.15, 0.16) is None
        assert keep_warm_minutes(water(temp=48.0), 0.16, 0.16) is None

    def test_a_threshold_at_or_above_the_target_gives_nothing_once_the_water_is_hot(self):
        assert keep_warm_minutes(water(temp=55.0, min_temp=50.0, gap=5.0), 0.38, 0.16) is None

    def test_it_is_at_least_five_minutes(self):
        assert keep_warm_minutes(water(temp=54.99, min_temp=54.0, gap=1.0), 0.38, 0.16) == 5
