"""A plugged-in Zappi charges in Fast mode inside the owner's charge window and goes back after."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.rules import (
    EVRequest,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    decide_ev_charger_action as _decide,
)
from custom_components.givenergy_inverter_manager.lib.ev import (
    CHEAP_RATE_MODE_DEFAULTS,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    pick_cheap_rate_mode,
)

OPTIONS = ("Fast", "Eco", "Eco+", "Stopped")


def decide_ev_charger_action(charger, soc, surplus, **request):
    return _decide(charger, soc, surplus, EVRequest(**request))


def _zappi(mode: str, *, plugged: bool = True, options=OPTIONS) -> EVCharger:
    return EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="123",
        display_name="Zappi (123)",
        state=EVChargerState.CONNECTED if plugged else EVChargerState.DISCONNECTED,
        charge_mode=mode,
        charge_mode_entity="select.zappi_123_charge_mode",
        charge_mode_options=options,
    )


class TestPicking:
    def test_the_zappi_grid_mode_is_fast(self):
        assert CHEAP_RATE_MODE_DEFAULTS[EVChargerBrand.ZAPPI] == "Fast"
        assert pick_cheap_rate_mode(EVChargerBrand.ZAPPI, OPTIONS) == "Fast"

    def test_nothing_is_picked_when_the_select_has_no_such_option(self):
        assert pick_cheap_rate_mode(EVChargerBrand.ZAPPI, ("Eco", "Eco+")) is None

    def test_a_brand_without_a_known_grid_mode_picks_nothing(self):
        assert pick_cheap_rate_mode(EVChargerBrand.OCPP, OPTIONS) is None

    def test_the_default_applies_before_the_options_are_read(self):
        assert _zappi("Eco+", options=None).cheap_rate_mode() == "Fast"


class TestTheDecision:
    def test_inside_the_window_a_plugged_in_car_gets_fast_even_with_no_surplus(self):
        target, reason = decide_ev_charger_action(_zappi("Eco+"), 60.0, 0.0, scheduled=True)
        assert target == "Fast"
        assert "Charge window" in reason

    def test_already_in_fast_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, scheduled=True)
        assert target is None

    def test_no_car_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(
            _zappi("Eco+", plugged=False), 60.0, 0.0, scheduled=True
        )
        assert target is None

    def test_outside_the_window_fast_is_never_selected(self):
        target, _ = decide_ev_charger_action(_zappi("Eco+"), 60.0, 3000.0)
        assert target is None

    def test_when_the_window_ends_a_charger_this_integration_set_goes_to_eco_plus(self):
        target, reason = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, scheduled=False, grid_held=True
        )
        assert target == "Eco+"
        assert "Charge window over" in reason

    def test_a_charger_in_fast_that_nothing_here_set_is_left_alone(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0)
        assert target is None

    def test_fast_is_left_alone_when_the_charger_has_no_surplus_mode(self):
        charger = _zappi("Fast", options=("Fast", "Eco"))
        target, reason = decide_ev_charger_action(charger, 60.0, 0.0, grid_held=True)
        assert target is None and "left" in reason

    def test_an_unplugged_charger_is_never_stopped(self):
        target, _ = decide_ev_charger_action(_zappi("Eco+", plugged=False), 60.0, 0.0)
        assert target is None

    def test_an_unplugged_charger_keeps_fast_while_the_window_is_open(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast", plugged=False), 60.0, 0.0, scheduled=True
        )
        assert target is None

    def test_a_charger_without_a_fast_option_keeps_the_solar_rule(self):
        charger = _zappi("Eco", options=("Eco", "Eco+", "Stopped"))
        target, _ = decide_ev_charger_action(charger, 60.0, 3000.0, scheduled=True)
        assert target == "Eco+"

    def test_outside_the_window_surplus_selects_eco_plus_and_a_small_one_changes_nothing(self):
        assert decide_ev_charger_action(_zappi("Stopped"), 60.0, 3000.0)[0] == "Eco+"
        assert decide_ev_charger_action(_zappi("Stopped"), 60.0, 1000.0)[0] is None
        assert decide_ev_charger_action(_zappi("Eco+"), 60.0, 3000.0)[0] is None


@pytest.mark.parametrize("surplus", [0.0, 500.0, 5000.0])
def test_the_window_wins_over_any_surplus(surplus):
    target, _ = decide_ev_charger_action(_zappi("Eco+"), 60.0, surplus, scheduled=True)
    assert target == "Fast"


class TestChargeNow:
    def test_it_selects_fast_outside_the_window_with_no_surplus(self):
        target, reason = decide_ev_charger_action(_zappi("Eco+"), 60.0, 0.0, charge_now=True)
        assert target == "Fast"
        assert "Charge now" in reason

    def test_already_in_fast_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, charge_now=True)
        assert target is None

    def test_it_keeps_the_grid_mode_while_it_is_on_even_if_this_integration_set_it(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, charge_now=True, grid_held=True
        )
        assert target is None

    def test_turning_it_off_takes_a_charger_it_set_back_to_eco_plus(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, grid_held=True, charge_now=False
        )
        assert target == "Eco+"

    def test_without_a_fast_mode_it_changes_nothing(self):
        charger = _zappi("Eco", options=("Eco", "Eco+", "Stopped"))
        target, _ = decide_ev_charger_action(charger, 60.0, 0.0, charge_now=True)
        assert target is None

    def test_with_no_car_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(
            _zappi("Eco+", plugged=False), 60.0, 0.0, charge_now=True
        )
        assert target is None


class TestPause:
    def test_it_selects_stopped_outside_the_window(self):
        target, reason = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 3000.0, charge_now=True, pause=True
        )
        assert target == "Stopped"
        assert "Paused" in reason

    def test_inside_the_window_the_schedule_wins_over_pause(self):
        target, _ = decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0, scheduled=True, pause=True)
        assert target == "Fast"

    def test_already_stopped_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0, pause=True)
        assert target is None

    def test_turning_it_off_leaves_a_stopped_charger_alone_until_there_is_surplus(self):
        assert decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0)[0] is None
        assert decide_ev_charger_action(_zappi("Stopped"), 60.0, 3000.0)[0] == "Eco+"

    def test_without_a_stopped_option_it_says_so(self):
        charger = _zappi("Eco+", options=("Fast", "Eco", "Eco+"))
        target, reason = decide_ev_charger_action(charger, 60.0, 0.0, pause=True)
        assert target is None and "Stopped mode" in reason
