"""The trigger state for the alternative heating: idle, keep_warm or start_now.

The tariff is 0.30 by day and 0.15 from 23:00 to 08:00, with no discount and no VAT. The water is
lifted at 10 degrees an hour toward 55, and the restart gap is 5 degrees.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.alt_heat_advice import (
    AdviceInputs,
    advise_water_heating,
)
from custom_components.givenergy_inverter_manager.core.alt_heat_start import WaterReading
from custom_components.givenergy_inverter_manager.core.alt_heat_trigger import (
    STATE_IDLE,
    STATE_KEEP_WARM,
    STATE_START_NOW,
    STATES,
    AltHeatTrigger,
    alt_heat_trigger,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

DUBLIN = ZoneInfo("Europe/Dublin")
TARIFF = build_tariff(
    {
        "base_rate": 0.30,
        "export_rate": 0.15,
        "vat_rate": 0,
        "discount_rate": 0,
        "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
    }
)
TARGET, RATE, MINIMUM, GAP = 55.0, 10.0, 45.0, 5.0
READY = (time(19, 0),)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 15, hour, minute, tzinfo=DUBLIN)


def water(temp: float) -> WaterReading:
    return WaterReading(temp, TARGET, RATE, MINIMUM, GAP)


def trigger(
    now: datetime, temp: float, *, alt: float = 0.20, ready: tuple = READY, solar: bool = False
) -> AltHeatTrigger:
    reading = water(temp)
    advice = advise_water_heating(
        AdviceInputs(
            tariff=TARIFF,
            now=now,
            alt_cost_per_kwh=alt,
            ready_times=ready,
            solar_surplus=solar,
            water=reading,
            scheduled_heating=bool(ready),
        )
    )
    return alt_heat_trigger(advice, reading, now)


class TestStartNow:
    def test_it_is_start_now_from_the_start_time_and_not_before(self):
        # Oil has to start at 15:32 to finish before the immersion would start at 17:16. Water
        # this cold is already past the lower boundary, so before then the state is keep_warm.
        assert trigger(at(15, 0), 40.0).state == STATE_KEEP_WARM
        assert trigger(at(15, 31), 40.0).state == STATE_KEEP_WARM

        due = trigger(at(15, 32), 40.0)

        assert due.state == STATE_START_NOW
        assert due.start_by == at(15, 32)
        assert due.run_minutes == 104
        assert due.saving_per_kwh == pytest.approx(0.10)

    def test_a_start_that_is_already_late_is_start_now_at_once(self):
        late = trigger(at(17, 30), 40.0)

        assert late.state == STATE_START_NOW
        assert late.start_by == at(17, 30)

    def test_it_stays_start_now_while_the_water_needs_heating(self):
        assert trigger(at(16, 30), 40.0).state == STATE_START_NOW

    def test_it_returns_to_idle_once_the_water_is_at_the_target(self):
        assert trigger(at(16, 30), 55.0).state == STATE_IDLE

    def test_it_is_idle_when_electricity_is_cheaper_than_the_alternative(self):
        assert trigger(at(15, 40), 40.0, alt=0.35).state == STATE_IDLE


class TestKeepWarm:
    def test_water_at_the_lower_boundary_with_a_cheaper_alternative_is_keep_warm(self):
        result = trigger(at(13, 0), 50.0, ready=())

        assert result.state == STATE_KEEP_WARM
        assert result.run_minutes is not None and result.run_minutes % 5 == 0
        assert result.saving_per_kwh == pytest.approx(0.10)
        assert result.start_by is None

    def test_water_above_the_boundary_is_idle(self):
        assert trigger(at(13, 0), 52.0, ready=()).state == STATE_IDLE

    def test_it_is_idle_when_the_alternative_is_not_cheaper_than_the_grid(self):
        assert trigger(at(13, 0), 50.0, alt=0.35, ready=()).state == STATE_IDLE

    def test_solar_surplus_heating_the_water_needs_no_other_heat(self):
        assert trigger(at(13, 0), 50.0, ready=(), solar=True).state == STATE_IDLE

    def test_a_higher_minimum_triggers_sooner(self):
        reading = WaterReading(TARGET - 6.0, TARGET, RATE, 52.0, GAP)
        advice = advise_water_heating(
            AdviceInputs(tariff=TARIFF, now=at(13, 0), alt_cost_per_kwh=0.20, water=reading)
        )

        assert alt_heat_trigger(advice, reading, at(13, 0)).state == STATE_KEEP_WARM


class TestPriorityAndNoAdvice:
    def test_a_due_ready_by_start_wins_over_keep_warm(self):
        both = trigger(at(17, 30), 45.0)

        assert both.state == STATE_START_NOW

    def test_no_advice_is_idle(self):
        assert alt_heat_trigger(None, None, at(12, 0)) == AltHeatTrigger()

    def test_no_water_reading_cannot_trigger_a_keep_warm_run(self):
        advice = advise_water_heating(
            AdviceInputs(tariff=TARIFF, now=at(13, 0), alt_cost_per_kwh=0.20, water=water(50.0))
        )

        assert alt_heat_trigger(advice, None, at(13, 0)).state == STATE_IDLE

    def test_the_states_are_the_three_the_sensor_offers(self):
        assert STATES == (STATE_IDLE, STATE_KEEP_WARM, STATE_START_NOW)
