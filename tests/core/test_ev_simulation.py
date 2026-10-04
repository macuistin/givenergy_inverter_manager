"""Multi-day simulation of the EV mode decision against a toy house and Zappi."""

from __future__ import annotations

import math

import pytest

from custom_components.givenergy_inverter_manager.const import EV_CHARGER_MIN_POWER_W
from custom_components.givenergy_inverter_manager.discovery import (
    ZAPPI_ECO_PLUS_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from tests.conftest import _raw, _run

CYCLE_S = 30
CYCLES_PER_DAY = 24 * 3600 // CYCLE_S
DAYS = 3
PLUG_IN_CYCLE = 8 * 3600 // CYCLE_S
UNPLUG_CYCLE = 18 * 3600 // CYCLE_S
SUNRISE_CYCLE = 6 * 3600 // CYCLE_S
SUNSET_CYCLE = 20 * 3600 // CYCLE_S
CAR_W = 3000.0
BASE_LOAD_W = 600.0
EMA_ALPHA = 0.5
ARRIVAL_MODE = "Stopped"
MAX_REQUESTS_PER_DAY = 1
MAX_SIGNAL_TRANSITIONS_PER_DAY = 2


def _daylight(cycle_of_day: int) -> float:
    if not SUNRISE_CYCLE <= cycle_of_day <= SUNSET_CYCLE:
        return 0.0
    span = SUNSET_CYCLE - SUNRISE_CYCLE
    return math.sin(math.pi * (cycle_of_day - SUNRISE_CYCLE) / span)


def _clear(cycle_of_day: int) -> float:
    return 5000.0 * _daylight(cycle_of_day)


def _broken_cloud(cycle_of_day: int) -> float:
    return _daylight(cycle_of_day) * (3500.0 + 1200.0 * math.sin(cycle_of_day * 0.9))


def _overcast(cycle_of_day: int) -> float:
    return 900.0 * _daylight(cycle_of_day)


WEATHER = (_clear, _broken_cloud, _overcast)


def _charger(mode: str, plugged: bool, power_w: float) -> EVCharger:
    if not plugged:
        state = EVChargerState.DISCONNECTED
    elif power_w > 0:
        state = EVChargerState.CHARGING
    else:
        state = EVChargerState.CONNECTED
    charger = EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="123",
        display_name="Zappi (123)",
        state=state,
        charge_mode=mode,
        charge_mode_entity="select.zappi_123_charge_mode",
    )
    charger.power_w = power_w
    return charger


def simulate(weather=WEATHER, days: int = DAYS, ev_inside_house_load: bool = False):
    """Run the real engine each cycle. Returns one record per cycle."""
    records = []
    mode = ARRIVAL_MODE
    smoothed = 0.0
    ev_w = 0.0
    for day in range(days):
        solar_fn = weather[day % len(weather)]
        for cycle in range(CYCLES_PER_DAY):
            plugged = PLUG_IN_CYCLE <= cycle < UNPLUG_CYCLE
            if cycle == PLUG_IN_CYCLE:
                mode = ARRIVAL_MODE
            if not plugged:
                ev_w = 0.0
            solar = solar_fn(cycle)
            smoothed = EMA_ALPHA * smoothed + EMA_ALPHA * solar
            house_load = BASE_LOAD_W + (ev_w if ev_inside_house_load else 0.0)
            raw = _raw(
                solar_power_w=solar,
                smoothed_solar_power_w=smoothed,
                house_load_w=house_load,
                battery_soc=90.0,
                battery_power_w=0.0,
                grid_power_w=max(0.0, house_load - solar),
                inverter_max_w=8000.0,
                ev_power_w=ev_w,
                ev_plugged_in=plugged,
            )
            data, target = _run(raw=raw, ev_charger=_charger(mode, plugged, ev_w))
            if target is not None:
                mode = target
            free_w = max(0.0, smoothed - BASE_LOAD_W)
            ev_w = min(CAR_W, free_w) if plugged and mode == ZAPPI_ECO_PLUS_MODE else 0.0
            if ev_w < EV_CHARGER_MIN_POWER_W:
                ev_w = 0.0
            records.append(
                {
                    "day": day,
                    "cycle": cycle,
                    "plugged": plugged,
                    "target": target,
                    "signal": data.ev_solar_surplus_available,
                    "surplus": data.net_solar_surplus_w,
                    "ev_w": ev_w,
                }
            )
    return records


def _transitions(values: list[bool]) -> int:
    return sum(1 for a, b in zip(values, values[1:], strict=False) if a != b)


@pytest.fixture(scope="module")
def outside_house_load():
    return simulate()


@pytest.fixture(scope="module")
def inside_house_load():
    return simulate(ev_inside_house_load=True)


@pytest.mark.parametrize("fixture", ["outside_house_load", "inside_house_load"])
class TestModeRequests:
    def test_at_most_one_request_per_day(self, fixture, request):
        records = request.getfixturevalue(fixture)
        for day in range(DAYS):
            requests = [r for r in records if r["day"] == day and r["target"] is not None]
            assert len(requests) <= MAX_REQUESTS_PER_DAY

    def test_only_ever_requests_eco_plus(self, fixture, request):
        records = request.getfixturevalue(fixture)
        assert {r["target"] for r in records if r["target"]} <= {ZAPPI_ECO_PLUS_MODE}

    def test_never_requests_while_unplugged(self, fixture, request):
        records = request.getfixturevalue(fixture)
        assert not [r for r in records if r["target"] and not r["plugged"]]

    def test_requests_only_with_enough_surplus(self, fixture, request):
        records = request.getfixturevalue(fixture)
        for r in records:
            if r["target"]:
                assert r["surplus"] >= EV_CHARGER_MIN_POWER_W

    def test_sunny_days_request_overcast_day_does_not(self, fixture, request):
        records = request.getfixturevalue(fixture)
        requested = {r["day"] for r in records if r["target"]}
        assert requested == {0, 1}


class TestSignalStability:
    @pytest.mark.parametrize("day", [0, 2])
    def test_signal_transitions_bounded_on_smooth_days(self, outside_house_load, day):
        signal = [r["signal"] for r in outside_house_load if r["day"] == day]
        assert _transitions(signal) <= MAX_SIGNAL_TRANSITIONS_PER_DAY

    def test_signal_matches_the_mode_decision_threshold(self, outside_house_load):
        for r in outside_house_load:
            assert r["signal"] == (r["surplus"] >= EV_CHARGER_MIN_POWER_W)

    def test_car_charges_on_the_sunny_days(self, outside_house_load):
        for day in (0, 1):
            assert any(r["ev_w"] > 0 for r in outside_house_load if r["day"] == day)
