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
    on_cheap_rate=False,
    rate_name="Day",
    rate=0.365,
    currency_symbol="€",
    in_extra_hours=False,
    charge_until=None,
    next_charge_start="23:00",
    next_cheap_start="23:00",
    next_cheap_name="Night",
    next_cheap_rate=0.18,
    surplus_min_w=1380,
)


def _plan(**changes) -> str:
    return ev_plan_text(replace(BASE, **changes))


def test_by_day_it_names_the_next_cheaper_rate_and_the_solar_option():
    text = _plan()
    assert "from 23:00 at the Night rate (€0.18/kWh)" in text
    assert "1380 W" in text


def test_in_a_cheaper_rate_it_says_when_that_ends():
    text = _plan(on_cheap_rate=True, rate_name="Night", rate=0.18, charge_until="07:00")
    assert text.startswith("Charging at the Night rate (€0.18/kWh) until 07:00")


def test_a_cheaper_rate_with_no_known_end_gives_no_time():
    text = _plan(on_cheap_rate=True, rate_name="Night", rate=0.18)
    assert " until " not in text


def test_charge_now_names_the_current_rate():
    assert "at your request, at the Day rate (€0.36/kWh)" in _plan(charge_now=True)


def test_pause_wins_over_everything():
    assert _plan(pause=True, charge_now=True, on_cheap_rate=True).startswith("Paused by you")


def test_without_a_car_it_says_to_plug_in():
    assert _plan(plugged_in=False).startswith("Plug the car in. It will charge from 23:00")


@pytest.mark.parametrize("plugged_in", [True, False])
def test_a_charger_with_no_grid_mode_is_solar_only(plugged_in):
    text = _plan(plugged_in=plugged_in, can_charge_from_grid=False)
    assert "solar" in text and "23:00" not in text


def test_with_no_cheaper_rate_in_the_tariff_it_waits_for_solar():
    assert _plan(next_cheap_start=None).startswith("Waiting for solar surplus of 1380 W")
    assert _plan(plugged_in=False, next_cheap_start=None) == "Plug the car in and it charges from solar surplus."


def test_an_earlier_start_names_both_times():
    text = _plan(next_charge_start="21:00")
    assert "from 21:00, with the Night rate (€0.18/kWh) from 23:00" in text


def test_the_extra_hours_are_named():
    assert "extra hours you allowed" in _plan(in_extra_hours=True)
