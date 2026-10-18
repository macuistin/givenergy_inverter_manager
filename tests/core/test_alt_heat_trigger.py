"""The two triggers for the alternative heating: the ready-by start and the low water run.

The tariff is 0.30 by day and 0.15 from 23:00 to 08:00, with no discount and no VAT. The water is
lifted at 10 degrees an hour toward 55, the minimum is 45 and the restart gap is 5 degrees, so the
immersion restarts at 50 and the lower boundary is 50.
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
    STATE_START_NOW,
    STATES,
    AltHeatTrigger,
    low_water_trigger,
    ready_by_trigger,
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


def inputs(
    now: datetime,
    temp: float,
    *,
    alt: float = 0.20,
    ready: tuple = READY,
    solar: bool = False,
    minimum: float = MINIMUM,
) -> AdviceInputs:
    return AdviceInputs(
        tariff=TARIFF,
        now=now,
        alt_cost_per_kwh=alt,
        ready_times=ready,
        solar_surplus=solar,
        water=WaterReading(temp, TARGET, RATE, minimum, GAP),
        scheduled_heating=bool(ready),
    )


def ready_by(now: datetime, temp: float, **kw) -> AltHeatTrigger:
    return ready_by_trigger(inputs(now, temp, **kw))


def low_water(now: datetime, temp: float, **kw) -> AltHeatTrigger:
    given = inputs(now, temp, **kw)
    return low_water_trigger(advise_water_heating(given), given)


class TestTheReadyByTrigger:
    def test_it_fires_at_the_start_time_and_not_before(self):
        # Oil has to start at 15:32 to finish before the immersion would start at 17:16.
        assert ready_by(at(15, 0), 40.0).state == STATE_IDLE
        assert ready_by(at(15, 31), 40.0).state == STATE_IDLE

        due = ready_by(at(15, 32), 40.0)

        assert due.state == STATE_START_NOW
        assert due.start_by == at(15, 32)
        assert due.ready_at == at(19, 0)
        assert due.run_minutes == 104
        assert due.saving_per_kwh == pytest.approx(0.10)

    @pytest.mark.parametrize(
        ("temp", "run", "start"),
        [(30.0, 173, at(13, 14)), (40.0, 104, at(15, 32)), (48.0, 49, at(17, 22))],
    )
    def test_the_colder_the_water_the_longer_the_run_and_the_earlier_the_start(
        self, temp, run, start
    ):
        due = ready_by(start, temp)

        assert (due.state, due.run_minutes, due.start_by) == (STATE_START_NOW, run, start)
        assert ready_by(at(12, 0), temp).state == STATE_IDLE

    def test_water_one_degree_below_the_target_gets_a_start_not_idle(self):
        # Above the immersion's restart threshold of 50, so the plan alone would do nothing. A
        # one degree lift is a 7 minute run, so the start is late and close to the ready time.
        assert ready_by(at(18, 45), 54.0).state == STATE_IDLE

        result = ready_by(at(18, 46), 54.0)

        assert result.state == STATE_START_NOW
        assert result.run_minutes == 7

    def test_water_less_than_a_degree_below_the_target_is_idle(self):
        assert ready_by(at(18, 50), 54.5).state == STATE_IDLE

    def test_water_at_the_target_is_idle(self):
        assert ready_by(at(16, 30), 55.0).state == STATE_IDLE

    def test_a_start_that_is_late_fires_at_once(self):
        assert ready_by(at(17, 30), 40.0).state == STATE_START_NOW

    def test_it_is_idle_when_electricity_is_cheaper_than_the_alternative(self):
        assert ready_by(at(15, 40), 40.0, alt=0.35).state == STATE_IDLE

    def test_it_is_idle_without_a_ready_time(self):
        assert ready_by(at(15, 40), 40.0, ready=()).state == STATE_IDLE

    def test_it_is_idle_without_the_immersion_schedule_to_fall_back_on(self):
        given = AdviceInputs(
            tariff=TARIFF,
            now=at(15, 40),
            alt_cost_per_kwh=0.20,
            ready_times=READY,
            water=WaterReading(40.0, TARGET, RATE, MINIMUM, GAP),
            scheduled_heating=False,
        )

        assert ready_by_trigger(given).state == STATE_IDLE

    def test_it_is_idle_without_a_water_reading(self):
        given = AdviceInputs(
            tariff=TARIFF, now=at(15, 40), alt_cost_per_kwh=0.20, ready_times=READY
        )

        assert ready_by_trigger(given).state == STATE_IDLE


class TestTheLowWaterTrigger:
    def test_water_at_the_lower_boundary_with_a_cheaper_alternative_fires(self):
        result = low_water(at(13, 0), 50.0, ready=())

        assert result.state == STATE_START_NOW
        assert result.run_minutes is not None and result.run_minutes % 5 == 0
        assert result.saving_per_kwh == pytest.approx(0.10)
        assert result.start_by is None

    def test_one_degree_above_the_boundary_it_still_fires(self):
        assert low_water(at(13, 0), 51.0, ready=()).state == STATE_START_NOW

    def test_more_than_a_degree_above_the_boundary_it_is_idle(self):
        assert low_water(at(13, 0), 51.5, ready=()).state == STATE_IDLE

    def test_it_fires_whatever_a_ready_time_says(self):
        assert low_water(at(13, 0), 50.0).state == STATE_START_NOW

    def test_it_is_idle_when_the_alternative_is_not_cheaper_than_the_grid(self):
        assert low_water(at(13, 0), 50.0, alt=0.35, ready=()).state == STATE_IDLE

    def test_solar_surplus_heating_the_water_needs_no_other_heat(self):
        assert low_water(at(13, 0), 50.0, ready=(), solar=True).state == STATE_IDLE

    def test_a_higher_minimum_makes_it_fire_sooner(self):
        # Minimum 52 and a gap of 5 put the boundary at the lower of 57 and 50, so use a gap
        # that makes the minimum the lower one instead.
        given = AdviceInputs(
            tariff=TARIFF,
            now=at(13, 0),
            alt_cost_per_kwh=0.20,
            water=WaterReading(TARGET - 3.0, TARGET, RATE, 50.0, 1.0),
        )

        # Boundary min(50 + 1, 55 - 1) = 51, and 52 is one degree above it.
        assert low_water_trigger(advise_water_heating(given), given).state == STATE_START_NOW

    def test_no_advice_or_no_water_reading_is_idle(self):
        given = inputs(at(13, 0), 50.0, ready=())

        assert low_water_trigger(None, given) == AltHeatTrigger()
        no_water = AdviceInputs(tariff=TARIFF, now=at(13, 0), alt_cost_per_kwh=0.20)
        assert low_water_trigger(advise_water_heating(no_water), no_water) == AltHeatTrigger()


def test_the_states_are_the_two_the_sensors_offer():
    assert STATES == (STATE_IDLE, STATE_START_NOW)
