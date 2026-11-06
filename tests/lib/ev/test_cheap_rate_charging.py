"""A plugged-in Zappi charges in Fast mode during a cheaper rate period and goes back after."""

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
    def test_a_cheaper_rate_with_a_plugged_in_car_selects_fast_even_with_no_surplus(self):
        target, reason = decide_ev_charger_action(_zappi("Eco+"), 60.0, 0.0, on_cheap_rate=True)
        assert target == "Fast"
        assert "Cheaper rate" in reason

    def test_already_in_fast_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, on_cheap_rate=True)
        assert target is None

    def test_no_car_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(
            _zappi("Eco+", plugged=False), 60.0, 0.0, on_cheap_rate=True
        )
        assert target is None

    def test_at_the_base_rate_fast_is_never_selected(self):
        target, _ = decide_ev_charger_action(_zappi("Eco+"), 60.0, 3000.0)
        assert target is None

    def test_when_the_cheaper_rate_ends_with_no_surplus_the_charger_is_stopped(self):
        target, reason = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, on_cheap_rate=False, mode_held=True
        )
        assert target == "Stopped"
        assert "Charge hours are over" in reason

    def test_when_the_cheaper_rate_ends_with_surplus_the_charger_goes_to_eco_plus(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 3000.0, on_cheap_rate=False)
        assert target == "Eco+"

    def test_a_charger_left_in_fast_by_hand_is_stopped_outside_the_charge_hours(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, on_cheap_rate=False)
        assert target == "Stopped"

    def test_fast_is_left_alone_when_the_charger_has_no_stop_or_surplus_mode(self):
        charger = _zappi("Fast", options=("Fast", "Eco"))
        target, reason = decide_ev_charger_action(charger, 60.0, 0.0)
        assert target is None and "left" in reason

    def test_an_unplugged_charger_in_eco_plus_is_stopped(self):
        target, _ = decide_ev_charger_action(_zappi("Eco+", plugged=False), 60.0, 0.0)
        assert target == "Stopped"

    def test_an_unplugged_charger_keeps_fast_while_a_cheaper_rate_runs(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast", plugged=False), 60.0, 0.0, on_cheap_rate=True
        )
        assert target is None

    def test_an_unplugged_charger_is_stopped_when_paused(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast", plugged=False), 60.0, 0.0, on_cheap_rate=True, pause=True
        )
        assert target == "Stopped"

    def test_an_unplugged_charger_without_a_stop_mode_is_left_alone(self):
        charger = _zappi("Fast", plugged=False, options=("Fast", "Eco", "Eco+"))
        target, _ = decide_ev_charger_action(charger, 60.0, 0.0)
        assert target is None

    def test_a_charger_without_a_fast_option_keeps_the_solar_rule(self):
        charger = _zappi("Eco", options=("Eco", "Eco+", "Stopped"))
        target, _ = decide_ev_charger_action(charger, 60.0, 3000.0, on_cheap_rate=True)
        assert target == "Eco+"


@pytest.mark.parametrize("surplus", [0.0, 500.0, 5000.0])
def test_the_cheaper_rate_wins_over_any_surplus(surplus):
    target, _ = decide_ev_charger_action(_zappi("Eco+"), 60.0, surplus, on_cheap_rate=True)
    assert target == "Fast"


class TestChargeNow:
    def test_it_selects_fast_at_the_base_rate_with_no_surplus(self):
        target, reason = decide_ev_charger_action(_zappi("Eco+"), 60.0, 0.0, charge_now=True)
        assert target == "Fast"
        assert "Charge now" in reason

    def test_already_in_fast_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, charge_now=True)
        assert target is None

    def test_turning_it_off_stops_a_charger_it_set_when_there_is_no_surplus(self):
        target, _ = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, mode_held=True, charge_now=False
        )
        assert target == "Stopped"

    def test_without_a_fast_mode_it_says_so_and_changes_nothing(self):
        charger = _zappi("Eco", options=("Eco", "Eco+", "Stopped"))
        target, reason = decide_ev_charger_action(charger, 60.0, 3000.0, charge_now=True)
        assert target is None and "Fast mode" in reason

    def test_with_no_car_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(
            _zappi("Eco+", plugged=False), 60.0, 0.0, charge_now=True
        )
        assert target is None


class TestPause:
    def test_it_selects_stopped_at_any_rate(self):
        target, reason = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 3000.0, on_cheap_rate=True, charge_now=True, pause=True
        )
        assert target == "Stopped"
        assert "Paused" in reason

    def test_already_stopped_nothing_is_sent(self):
        target, _ = decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0, pause=True)
        assert target is None

    def test_turning_it_off_puts_a_charger_it_stopped_back_to_eco_plus(self):
        target, _ = decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0, mode_held=True)
        assert target == "Eco+"

    def test_a_charger_the_owner_stopped_by_hand_is_left_alone(self):
        target, _ = decide_ev_charger_action(_zappi("Stopped"), 60.0, 0.0)
        assert target is None

    def test_without_a_stopped_option_it_says_so(self):
        charger = _zappi("Eco+", options=("Fast", "Eco", "Eco+"))
        target, reason = decide_ev_charger_action(charger, 60.0, 0.0, pause=True)
        assert target is None and "Stopped mode" in reason
