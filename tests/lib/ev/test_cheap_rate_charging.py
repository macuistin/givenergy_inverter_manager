"""A plugged-in Zappi charges in Fast mode during a cheaper rate period and goes back after."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.rules import decide_ev_charger_action
from custom_components.givenergy_inverter_manager.lib.ev import (
    CHEAP_RATE_MODE_DEFAULTS,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    pick_cheap_rate_mode,
)

OPTIONS = ("Fast", "Eco", "Eco+", "Stopped")


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

    def test_when_the_cheaper_rate_ends_a_charger_this_rule_set_goes_back_to_eco_plus(self):
        target, reason = decide_ev_charger_action(
            _zappi("Fast"), 60.0, 0.0, on_cheap_rate=False, cheap_rate_charging=True
        )
        assert target == "Eco+"
        assert "over" in reason

    def test_a_charger_the_owner_put_in_fast_by_hand_is_left_alone(self):
        target, _ = decide_ev_charger_action(_zappi("Fast"), 60.0, 0.0, on_cheap_rate=False)
        assert target is None

    def test_a_charger_without_a_fast_option_keeps_the_solar_rule(self):
        charger = _zappi("Eco", options=("Eco", "Eco+", "Stopped"))
        target, _ = decide_ev_charger_action(charger, 60.0, 3000.0, on_cheap_rate=True)
        assert target == "Eco+"


@pytest.mark.parametrize("surplus", [0.0, 500.0, 5000.0])
def test_the_cheaper_rate_wins_over_any_surplus(surplus):
    target, _ = decide_ev_charger_action(_zappi("Eco+"), 60.0, surplus, on_cheap_rate=True)
    assert target == "Fast"
