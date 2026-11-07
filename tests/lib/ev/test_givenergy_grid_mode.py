"""A GivEnergy charger left in Grid is taken out of it when nothing asks for it."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.rules import (
    EVRequest,
    decide_ev_charger_action,
)
from custom_components.givenergy_inverter_manager.lib.ev import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)

OPTIONS = ("Eco", "Solar", "Grid", "Hybrid")


def _evc(mode: str, *, options=OPTIONS, plugged: bool = True) -> EVCharger:
    return EVCharger(
        brand=EVChargerBrand.GIVENERGY,
        name="GivEVC",
        serial="1",
        display_name="GivEnergy charger",
        state=EVChargerState.CONNECTED if plugged else EVChargerState.DISCONNECTED,
        charge_mode=mode,
        charge_mode_entity="select.givtcp_evc_charging_mode",
        charge_mode_options=options,
    )


def test_grid_is_named_as_the_mode_to_leave():
    assert _evc("Grid").grid_mode() == "Grid"
    assert _evc("Grid", options=None).grid_mode() == "Grid"


def test_a_charger_without_a_grid_option_has_none_to_leave():
    assert _evc("Solar", options=("Eco", "Solar")).grid_mode() is None


def test_grid_is_never_chosen_for_a_cheaper_rate():
    charger = _evc("Solar")
    assert charger.cheap_rate_mode() is None
    mode, _ = decide_ev_charger_action(charger, 50, 0, EVRequest(on_cheap_rate=True))
    assert mode is None


def test_grid_with_low_surplus_goes_back_to_solar():
    mode, reason = decide_ev_charger_action(_evc("Grid"), 50, 0, EVRequest())
    assert mode == "Solar"
    assert "Solar" in reason


def test_grid_with_enough_surplus_is_left_to_the_surplus_rule():
    mode, _ = decide_ev_charger_action(_evc("Grid"), 50, 2000, EVRequest())
    assert mode == "Solar"


def test_solar_is_left_alone_with_low_surplus():
    mode, _ = decide_ev_charger_action(_evc("Solar"), 50, 0, EVRequest())
    assert mode is None


def test_an_unplugged_charger_is_left_alone():
    mode, _ = decide_ev_charger_action(_evc("Grid", plugged=False), 50, 0, EVRequest())
    assert mode is None
