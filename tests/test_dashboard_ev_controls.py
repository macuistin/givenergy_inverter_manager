"""Charge now and Pause show on the main page and the EV view only while a car is plugged in."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.devices import Device
from tests.dashboard_support import default_entity_ids, devices_of, view_cards
from tests.dashboard_visibility import generated_for, install, seen, states_with

IDS = default_entity_ids()
CONTROLS = {"Charge now", "Pause"}


def _controls_seen(car_state: str, view: str) -> set[str]:
    config, brand = install(ev=True)
    generated = generated_for(ev=True)
    states = states_with(devices_of(config, brand), {IDS["ev_charger_state"]: car_state})
    shown = seen(generated, states)
    page = next(v for v in shown["views"] if v["path"] == view)
    return {c["name"] for c in view_cards(page) if c["type"] == "tile"} & CONTROLS


@pytest.mark.parametrize("view", ["power-flow", "ev-charger"])
@pytest.mark.parametrize("car_state", ["disconnected", "unknown"])
def test_no_unplugged_car_gets_the_buttons(view, car_state):
    assert _controls_seen(car_state, view) == set()


@pytest.mark.parametrize("view", ["power-flow", "ev-charger"])
@pytest.mark.parametrize("car_state", ["connected", "paused", "charging"])
def test_a_plugged_in_car_gets_both(view, car_state):
    assert _controls_seen(car_state, view) == CONTROLS


def test_the_ev_view_is_still_there_without_the_buttons():
    config, brand = install(ev=True)
    states = states_with(devices_of(config, brand), {IDS["ev_charger_state"]: "disconnected"})
    shown = seen(generated_for(ev=True), states)
    assert next(v for v in shown["views"] if v["path"] == "ev-charger")["sections"]
    assert Device.EV_CHARGER in devices_of(config, brand)
