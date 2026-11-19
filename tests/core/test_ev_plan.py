"""The car's charging plan reads as a sentence for each situation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.givenergy_inverter_manager.core.ev_plan import EVPlanFacts, ev_plan_text

BASE = EVPlanFacts(
    plugged_in=True,
    can_charge_from_grid=True,
    charge_now=False,
    pause=False,
    in_window=False,
    window_start="23:00",
    window_end="09:00",
    surplus_min_w=1380,
)


def _plan(**changes) -> str:
    return ev_plan_text(replace(BASE, **changes))


def test_outside_the_window_it_names_the_hours_and_the_solar_option():
    text = _plan()
    assert "charges from 23:00 to 09:00" in text
    assert "1380 W" in text


def test_in_the_window_it_says_when_the_schedule_ends():
    text = _plan(in_window=True)
    assert text.startswith("Charging on your schedule until 09:00")


def test_in_the_window_pause_changes_nothing_and_the_plan_says_so():
    text = _plan(in_window=True, pause=True, charge_now=True)
    assert text.startswith("Charging on your schedule until 09:00")
    assert "Pause is ignored in this window" in text


def test_outside_the_window_pause_wins_over_charge_now():
    assert _plan(pause=True, charge_now=True).startswith("Paused by you")


def test_charge_now_outside_the_window_carries_on_until_it_is_turned_off():
    assert "at your request" in _plan(charge_now=True)


def test_without_a_car_it_says_to_plug_in():
    assert _plan(plugged_in=False).startswith("Plug the car in. It charges from 23:00 to 09:00")
    assert _plan(plugged_in=False, in_window=True) == "Plug the car in and it charges until 09:00."


@pytest.mark.parametrize("plugged_in", [True, False])
def test_a_charger_with_no_grid_mode_is_solar_only(plugged_in):
    text = _plan(plugged_in=plugged_in, can_charge_from_grid=False, in_window=True)
    assert "solar" in text and "23:00" not in text


def test_without_a_car_reading_the_plan_says_nothing_about_the_car():
    assert "car is" not in _plan().lower()


def test_a_car_level_without_a_battery_size_gives_the_percentage_only():
    text = _plan(car_level_pct=38.0)
    assert text.endswith("The car is at 38%.")


def test_a_car_level_with_a_battery_size_gives_the_energy_it_needs():
    text = _plan(car_level_pct=38.0, car_missing_kwh=38.5)
    assert text.endswith("The car is at 38%, about 38 kWh to reach 100%.")


def test_a_full_car_says_it_is_full():
    assert _plan(car_level_pct=100.0, car_missing_kwh=0.0).endswith("The car is full.")


def test_the_car_level_follows_a_paused_plan_too():
    text = _plan(pause=True, car_level_pct=50.0)
    assert text.startswith("Paused by you.")
    assert text.endswith("The car is at 50%.")
