"""Unit tests for heating the immersion in the cheapest rate window (core, no Home Assistant)."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.const import SENSOR_OUTAGE_HOLD_LIMIT_S
from custom_components.givenergy_inverter_manager.core.immersion_window import (
    open_cheapest_window,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    CheapWindow,
    ImmersionInputs,
    ImmersionRun,
    PowerReadings,
    WaterState,
    should_divert_to_immersion,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

BASE_RATE = 0.3334
LABEL = "Nightboost 02:00 to 04:00"


def _tariff(*periods: tuple[str, float, str, str], base: float = BASE_RATE):
    return build_tariff(
        {
            "base_rate": base,
            "rate_periods": [
                {"name": n, "rate": r, "start": s, "end": e} for n, r, s, e in periods
            ],
        }
    )


NIGHT = ("Night", 0.1644, "23:00", "08:00")
BOOST = ("Nightboost", 0.0965, "02:00", "04:00")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 12, 15, hour, minute)


class TestOpenCheapestWindow:
    @pytest.mark.parametrize(
        ("hour", "minute", "is_open"),
        [(1, 59, False), (2, 0, True), (3, 59, True), (4, 0, False), (12, 0, False)],
    )
    def test_open_only_inside_the_cheapest_period(self, hour, minute, is_open):
        label = open_cheapest_window(_tariff(NIGHT, BOOST), at(hour, minute))
        assert (label == LABEL) is is_open
        assert (label is None) is not is_open

    def test_the_wider_dearer_period_is_not_the_window(self):
        assert open_cheapest_window(_tariff(NIGHT, BOOST), at(0, 30)) is None

    def test_a_period_across_midnight_is_open_on_both_sides_of_it(self):
        tariff = _tariff(("Night", 0.1, "23:00", "05:00"))
        assert open_cheapest_window(tariff, at(23, 30)) == "Night 23:00 to 05:00"
        assert open_cheapest_window(tariff, at(4, 30)) == "Night 23:00 to 05:00"

    def test_a_flat_rate_tariff_has_no_window(self):
        assert open_cheapest_window(_tariff(), at(3)) is None

    def test_a_timed_period_dearer_than_the_base_rate_is_not_cheap(self):
        tariff = _tariff(("Peak", 0.5, "17:00", "19:00"))
        assert open_cheapest_window(tariff, at(18)) is None


def water(
    temp: float | None = 40.0,
    *,
    target: float = 55.0,
    minimum: float = 30.0,
    gap: float = 5.0,
    unavailable: bool = False,
) -> WaterState:
    return WaterState(
        temp=temp,
        target_temp=target,
        min_temp=minimum,
        hysteresis_c=gap,
        temp_unavailable=unavailable,
    )


def decide(
    *,
    water: WaterState,
    window: CheapWindow | None = None,
    on: bool = False,
    unavailable_for_s: float = 0.0,
    switch: bool = True,
    solar_w: float | None = 0.0,
    soc: float = 20.0,
) -> tuple[bool, str]:
    return should_divert_to_immersion(
        ImmersionInputs(
            power=PowerReadings(
                solar_power_w=solar_w,
                house_load_w=400.0 if solar_w is not None else None,
                battery_power_w=0.0 if solar_w is not None else None,
                battery_soc=soc,
                inverter_max_w=5000.0,
                immersion_power_w=3000.0,
            ),
            water=water,
            run=ImmersionRun(
                currently_on=on, unavailable_for_s=unavailable_for_s, switch_configured=switch
            ),
            window=window if window is not None else CheapWindow(enabled=True, open_label=LABEL),
        )
    )


class TestHeatingStartsInTheWindow:
    def test_cold_water_heats_at_night_with_no_solar_and_a_flat_battery(self):
        heat, reason = decide(water=water(40.0))
        assert heat is True
        assert LABEL in reason

    def test_water_at_the_target_does_nothing(self):
        assert decide(water=water(55.0))[0] is False

    def test_water_above_the_target_does_nothing(self):
        assert decide(water=water(58.0), on=True)[0] is False

    def test_warm_water_from_yesterdays_solar_does_nothing(self):
        assert decide(water=water(54.0))[0] is False

    def test_water_inside_the_restart_gap_is_left_alone_until_it_cools(self):
        assert decide(water=water(51.0))[0] is False
        assert decide(water=water(49.9))[0] is True

    def test_a_running_heater_carries_on_to_the_target(self):
        assert decide(water=water(53.0), on=True)[0] is True
        assert decide(water=water(55.0), on=True)[0] is False

    def test_the_window_ignores_the_battery_level_and_the_power_sensors(self):
        assert decide(water=water(40.0), soc=5.0, solar_w=None)[0] is True


class TestHeatingOutsideTheWindow:
    def test_a_closed_window_leaves_the_surplus_rule_in_charge(self):
        window = CheapWindow(enabled=True, open_label=None)
        assert decide(water=water(40.0), window=window)[0] is False

    def test_a_closed_window_still_diverts_solar(self):
        window = CheapWindow(enabled=True, open_label=None)
        assert decide(water=water(40.0), window=window, solar_w=4000.0, soc=90.0)[0] is True

    def test_switched_off_the_window_does_nothing(self):
        window = CheapWindow(enabled=False, open_label=LABEL)
        assert decide(water=water(40.0), window=window)[0] is False

    def test_no_immersion_switch_means_nothing_is_scheduled(self):
        heat, reason = decide(water=water(40.0), switch=False)
        assert heat is False
        assert "No immersion switch" in reason


class TestNoTemperatureSensor:
    def test_nothing_is_scheduled_without_a_sensor(self):
        assert decide(water=water(None))[0] is False

    def test_solar_diversion_still_runs_without_a_sensor(self):
        assert decide(water=water(None), solar_w=4000.0, soc=90.0)[0] is True


class TestSensorOutage:
    def test_never_starts_while_the_reading_is_unavailable(self):
        heat, reason = decide(water=water(None, unavailable=True))
        assert heat is False
        assert "not starting" in reason

    def test_a_running_heater_is_held_for_the_outage_limit_then_stops(self):
        held = decide(water=water(None, unavailable=True), on=True, unavailable_for_s=60.0)
        assert held[0] is True
        stopped = decide(
            water=water(None, unavailable=True),
            on=True,
            unavailable_for_s=SENSOR_OUTAGE_HOLD_LIMIT_S,
        )
        assert stopped[0] is False


class TestSafety:
    def test_below_the_minimum_the_existing_rule_still_heats_and_names_itself(self):
        heat, reason = decide(water=water(29.0, minimum=30.0))
        assert heat is True
        assert "below minimum safe temperature" in reason

    def test_the_target_caps_the_window_run(self):
        assert decide(water=water(55.0), on=True)[0] is False


class TestDeviceCutsOutDuringTheWindow:
    """The heater's own auto-off switched it off with the water still below target."""

    def test_the_run_restarts_while_the_water_is_below_target(self):
        latched = CheapWindow(enabled=True, open_label=LABEL, heating_before=True)
        # 52 °C is inside the restart gap, so a fresh start would not heat. The run is carried on.
        assert decide(water=water(52.0), window=latched, on=False)[0] is True

    def test_a_finished_run_does_not_restart_inside_the_gap(self):
        assert decide(water=water(54.0), on=False)[0] is False

    def test_the_restart_still_stops_at_the_target(self):
        latched = CheapWindow(enabled=True, open_label=LABEL, heating_before=True)
        assert decide(water=water(55.0), window=latched, on=False)[0] is False

    def test_the_run_ends_with_the_window(self):
        closed = CheapWindow(enabled=True, open_label=None, heating_before=True)
        assert decide(water=water(52.0), window=closed, on=False)[0] is False


class TestThroughTheEngine:
    """The engine wires the opt-in, the tariff and the clock into the decision."""

    @staticmethod
    def _run_at(hour: int, minute: int = 0, **raw):
        from tests.conftest import _raw, _run

        fields = {
            "solar_power_w": 0.0,
            "battery_soc": 20.0,
            "immersion_temp": 40.0,
            "immersion_min_temp": 30.0,
        }
        fields.update(raw)
        return _run(raw=_raw(**fields), now=datetime(2026, 12, 15, hour, minute))[0]

    def test_opted_in_water_is_heated_at_the_window_start(self):
        data = self._run_at(2, 0, immersion_cheap_window_enabled=True)
        assert data.should_divert_immersion is True
        assert data.immersion_window_heating is True
        assert "Nightboost 02:00 to 04:00" in data.divert_reason

    def test_the_heater_stops_when_the_window_ends(self):
        data = self._run_at(4, 0, immersion_cheap_window_enabled=True, immersion_on=True)
        assert data.should_divert_immersion is False
        assert data.immersion_window_heating is False

    def test_not_opted_in_nothing_is_scheduled(self):
        data = self._run_at(2, 0)
        assert data.should_divert_immersion is False
        assert data.immersion_window_heating is False

    def test_warm_water_is_left_alone(self):
        data = self._run_at(2, 0, immersion_cheap_window_enabled=True, immersion_temp=56.0)
        assert data.should_divert_immersion is False

    def test_a_manual_off_override_beats_the_window(self):
        from tests.conftest import _raw, _run

        raw = _raw(
            solar_power_w=0.0,
            immersion_temp=40.0,
            immersion_min_temp=30.0,
            immersion_cheap_window_enabled=True,
        )
        data = _run(raw=raw, now=datetime(2026, 12, 15, 2, 30), override_immersion=False)[0]
        assert data.should_divert_immersion is False
        assert data.immersion_window_heating is False

    def test_no_switch_configured_schedules_nothing(self):
        data = self._run_at(
            2, 0, immersion_cheap_window_enabled=True, immersion_switch_configured=False
        )
        assert data.should_divert_immersion is False
