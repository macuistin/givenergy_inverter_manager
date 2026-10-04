"""Multi-cycle simulation of the immersion divert decision against a toy house."""

from __future__ import annotations

import math

import pytest

from custom_components.givenergy_inverter_manager.const import GIVTCP_MIN_WRITE_INTERVAL_S
from custom_components.givenergy_inverter_manager.core.rules import should_divert_to_immersion

CYCLES = 200
CYCLE_S = 30
ELEMENT_W = 3000.0
BASE_LOAD_W = 700.0
EMA_ALPHA = 0.5
MAX_TRANSITIONS = 4


def _clear_sky(i: int) -> float:
    return 5000.0 * math.sin(math.pi * i / (CYCLES - 1))


def _broken_cloud(i: int) -> float:
    return 3500.0 + 1200.0 * math.sin(i * 0.9)


def _kettle_base(i: int) -> float:
    return BASE_LOAD_W + (2000.0 if i % 40 < 4 else 0.0)


def _flat_base(_i: int) -> float:
    return BASE_LOAD_W


def simulate(
    solar_fn,
    base_fn=_flat_base,
    start_temp: float = 40.0,
    heat_c_per_cycle: float = 0.02,
    element_w: float = ELEMENT_W,
    decision_element_w: float | None = None,
    dropout=None,
):
    """Run the real decision function. Returns (on_states, temps, reasons)."""
    decision_w = element_w if decision_element_w is None else decision_element_w
    on = False
    temp = start_temp
    smoothed = 0.0
    outage_s = 0.0
    states, temps, reasons = [], [], []
    for i in range(CYCLES):
        solar = solar_fn(i)
        house_load = base_fn(i) + (element_w if on else 0.0)
        missing = dropout(i) if dropout else set()
        outage_s = outage_s + CYCLE_S if missing else 0.0
        smoothed = EMA_ALPHA * smoothed + EMA_ALPHA * solar if "solar" not in missing else smoothed
        on, reason = should_divert_to_immersion(
            solar_power_w=None if "solar" in missing else smoothed,
            house_load_w=None if "house_load" in missing else house_load,
            battery_soc=90.0,
            battery_power_w=None if "battery_power" in missing else 0.0,
            inverter_max_w=8000.0,
            immersion_temp=None if "temp" in missing else temp,
            immersion_target_temp=55.0,
            immersion_min_temp=30.0,
            currently_on=on,
            immersion_power_w=decision_w,
            immersion_temp_unavailable="temp" in missing,
            unavailable_for_s=outage_s,
        )
        if on:
            temp += heat_c_per_cycle
        states.append(on)
        temps.append(temp)
        reasons.append(reason)
    return states, temps, reasons


def transitions(states: list[bool]) -> int:
    return sum(1 for a, b in zip(states, states[1:], strict=False) if a != b)


def shortest_run(states: list[bool]) -> int:
    runs, count = [], 1
    for a, b in zip(states, states[1:], strict=False):
        if a == b:
            count += 1
        else:
            runs.append(count)
            count = 1
    runs.append(count)
    return min(runs[1:-1], default=CYCLES)


class TestStableOperation:
    def test_clear_sky_day_switches_few_times(self):
        states, _, _ = simulate(_clear_sky)
        assert any(states)
        assert transitions(states) <= MAX_TRANSITIONS

    def test_broken_cloud_with_kettle_switches_few_times(self):
        states, _, _ = simulate(_broken_cloud, _kettle_base)
        assert any(states)
        assert transitions(states) <= MAX_TRANSITIONS

    def test_no_short_runs_on_broken_cloud(self):
        states, _, _ = simulate(_broken_cloud, _kettle_base)
        assert shortest_run(states) >= 10

    def test_stops_at_target_and_does_not_restart(self):
        states, temps, _ = simulate(
            lambda _i: 5000.0, heat_c_per_cycle=0.2, start_temp=45.0
        )
        assert transitions(states) <= MAX_TRANSITIONS
        assert not states[-1]
        assert max(temps) < 55.3

    def test_element_stays_on_through_steady_surplus(self):
        states, _, _ = simulate(lambda _i: 4500.0)
        first_on = states.index(True)
        assert all(states[first_on:])

    def test_legacy_calculation_flaps(self):
        """Without adding the element's draw back, the same house flaps."""
        states, _, _ = simulate(lambda _i: 3000.0, decision_element_w=0.0)
        assert transitions(states) > 10

    def test_same_house_is_stable_with_own_draw_added_back(self):
        states, _, _ = simulate(lambda _i: 3000.0)
        assert transitions(states) <= MAX_TRANSITIONS


class TestDropouts:
    @pytest.mark.parametrize("sensor", ["house_load", "battery_power", "solar", "temp"])
    def test_dropout_while_off_never_starts(self, sensor):
        states, _, reasons = simulate(
            lambda _i: 0.0 if _i < 60 else 5000.0,
            dropout=lambda i: {sensor} if 60 <= i < 70 else set(),
        )
        assert not any(states[60:70])
        assert all("sensor unavailable" in r.lower() for r in reasons[60:70])
        assert any(states[70:])

    @pytest.mark.parametrize("sensor", ["house_load", "battery_power", "solar", "temp"])
    def test_short_dropout_while_on_does_not_switch_off(self, sensor):
        states, _, _ = simulate(
            lambda _i: 5000.0,
            dropout=lambda i: {sensor} if 50 <= i < 54 else set(),
        )
        assert all(states[10:])
        assert transitions(states) <= 1

    @pytest.mark.parametrize("sensor", ["house_load", "battery_power", "solar", "temp"])
    def test_long_dropout_while_on_turns_off_after_hold_limit(self, sensor):
        start = 50
        states, _, reasons = simulate(
            lambda _i: 5000.0,
            dropout=lambda i: {sensor} if i >= start else set(),
        )
        hold_cycles = GIVTCP_MIN_WRITE_INTERVAL_S // CYCLE_S
        off_at = start + hold_cycles - 1
        assert all(states[start:off_at])
        assert not any(states[off_at:])
        assert "turning off" in reasons[off_at]
        assert transitions(states) <= MAX_TRANSITIONS

    def test_hold_clock_restarts_after_recovery(self):
        gap = GIVTCP_MIN_WRITE_INTERVAL_S // CYCLE_S - 2
        states, _, _ = simulate(
            lambda _i: 5000.0,
            dropout=lambda i: {"house_load"} if i % (gap + 2) < gap else set(),
        )
        assert all(states[10:])

    def test_all_sensors_down_all_day_never_starts(self):
        states, _, _ = simulate(
            lambda _i: 5000.0,
            dropout=lambda _i: {"house_load", "battery_power", "solar", "temp"},
        )
        assert not any(states)

    def test_repeated_dropouts_do_not_flap(self):
        states, _, _ = simulate(
            _clear_sky,
            dropout=lambda i: {"house_load"} if i % 25 < 3 else set(),
        )
        assert transitions(states) <= MAX_TRANSITIONS

    def test_legionella_protection_survives_load_dropout(self):
        states, _, _ = simulate(
            lambda _i: 0.0,
            start_temp=20.0,
            dropout=lambda _i: {"house_load", "battery_power"},
        )
        assert states[0]
