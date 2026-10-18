"""A scheduled immersion run stops at the longest run time, over many engine cycles.

The cheapest rate window opens at 23:00 and the user has opted in to heating in it, so the
heater wants to run until the water is at its target. The water here does not warm, as with an
element that is failing, so without a limit the run never ends and the limit is what stops it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.givenergy_inverter_manager.core.scheduled_run import HeldScheduledRun
from tests.conftest import _raw, _run

CFG = {
    "base_rate": 0.30,
    "export_rate": 0.15,
    "vat_rate": 0,
    "discount_rate": 0,
    "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
}
START = datetime(2031, 1, 15, 22, 59, 30)
STEP = timedelta(seconds=30)


class Heater:
    """A heater that follows each verdict, run through the engine every 30 seconds."""

    def __init__(self, limit=60, **raw):
        self.held = HeldScheduledRun()
        self.limit = limit
        self.raw = raw
        self.on = False
        self.now = START
        self.minutes_on = 0.0
        self.last = None

    def step(self, **raw):
        fields = {
            "solar_power_w": 0.0,
            "house_load_w": 400.0,
            "battery_soc": 20.0,
            "immersion_schedule_enabled": True,
            "immersion_temp": 40.0,
            "immersion_target_temp": 55.0,
            "immersion_min_temp": 30.0,
            "immersion_hysteresis_c": 5.0,
            "immersion_max_run_minutes": self.limit,
            "immersion_on": self.on,
            **self.raw,
            **raw,
        }
        data = _run(raw=_raw(**fields), cfg=CFG, now=self.now, held_scheduled_run=self.held)[0]
        self.on = data.should_divert_immersion
        self.minutes_on += 0.5 if self.on else 0.0
        self.last = data
        self.now += STEP
        return data

    def until(self, hour, minute=0, **raw):
        stop = self.now.replace(hour=hour, minute=minute)
        if stop < self.now:
            stop += timedelta(days=1)
        while self.now < stop:
            self.step(**raw)
        return self.last


class TestTheRunStopsAtTheLimit:
    def test_the_heater_runs_for_the_limit_and_then_stops(self):
        heater = Heater(limit=60)
        heater.until(0, 30)
        assert 60 <= heater.minutes_on <= 61
        assert heater.on is False

    def test_the_reason_says_why_it_stopped(self):
        heater = Heater(limit=60)
        data = heater.until(0, 30)
        assert data.divert_reason == "Scheduled heating stopped: the run reached its longest time"

    def test_it_does_not_start_again_while_the_window_is_still_open(self):
        heater = Heater(limit=60)
        heater.until(0, 30)
        used = heater.minutes_on
        heater.until(7, 59)
        assert heater.minutes_on == used

    def test_a_shorter_limit_stops_it_sooner(self):
        heater = Heater(limit=20)
        heater.until(0, 30)
        assert 20 <= heater.minutes_on <= 21

    def test_without_a_limit_the_run_carries_on(self):
        heater = Heater(limit=0)
        heater.until(2, 0)
        assert heater.on is True
        assert heater.minutes_on > 170

    def test_water_that_is_warm_enough_is_not_heated_and_nothing_is_counted(self):
        heater = Heater(limit=60, immersion_temp=52.0)
        heater.until(1, 0)
        assert heater.minutes_on == 0.0
        assert heater.held.minutes == 0.0


class TestSolarSurplusIsNotLimited:
    def test_surplus_keeps_the_heater_on_after_the_scheduled_run_reached_its_limit(self):
        heater = Heater(limit=60)
        heater.until(0, 30)
        assert heater.on is False
        data = heater.step(solar_power_w=5000.0, battery_soc=95.0, house_load_w=500.0)
        assert data.should_divert_immersion is True
        assert "diverting to immersion" in data.divert_reason


class TestWhenTheLimitClears:
    def test_it_clears_when_the_window_closes(self):
        heater = Heater(limit=60)
        heater.until(0, 30)
        assert heater.held.capped
        heater.until(8, 1)
        assert not heater.held.capped
        assert heater.held.minutes == 0.0
