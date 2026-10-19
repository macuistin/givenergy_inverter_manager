"""The GivEnergy EV charger, as GivTCP publishes it: discovery, states, and the surplus mode.

The entity names and the state strings are GivTCP's own (its datapoint reference and its EVC
source), put into fixtures by givtcp_mock/systems/build.py. No real GivEnergy charger
has been read, so the entity ids and the prefix are a reading of the documentation.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest
from givtcp_mock import systems as fixtures

from custom_components.givenergy_inverter_manager.core.rules import decide_ev_charger_action
from custom_components.givenergy_inverter_manager.lib.ev import (
    FORBIDDEN_MODE_WORDS,
    SURPLUS_MODE_DEFAULTS,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    discover_ev_chargers,
    pick_surplus_mode,
    update_charger_state,
)

PREFIX = "givtcp_evc_ev1234a567"


@pytest.fixture(autouse=True)
def _reset_missing_power_warnings():
    from custom_components.givenergy_inverter_manager.lib.ev import discover as ev_charger

    ev_charger._WARNED_MISSING_POWER.clear()
    yield
    ev_charger._WARNED_MISSING_POWER.clear()


def _charger_only() -> dict:
    return fixtures.states("givenergy_charger_only")


def _found(states: dict) -> EVCharger:
    [charger] = [c for c in discover_ev_chargers(states) if c.brand is EVChargerBrand.GIVENERGY]
    return charger


class TestDiscovery:
    def test_it_is_found_with_every_entity_the_plan_needs(self):
        charger = _found(_charger_only())
        assert charger.serial == "EV1234A567"
        assert charger.display_name == "GivEnergy EVC (EV1234A567)"
        assert charger.status_entity == f"sensor.{PREFIX}_connection_status"
        assert charger.activity_entity == f"sensor.{PREFIX}_charging_state"
        assert charger.power_entity == f"sensor.{PREFIX}_active_power"
        assert charger.session_energy_entity == f"sensor.{PREFIX}_charge_session_energy"
        assert charger.charge_mode_entity == f"select.{PREFIX}_charging_mode"
        assert charger.is_fully_discovered

    def test_it_never_holds_the_controls_the_integration_must_not_touch(self):
        charger = _found(_charger_only())
        owned = {v for v in vars(charger).values() if isinstance(v, str)}
        assert not any("charge_control" in v or "plug_and_go" in v for v in owned)

    def test_a_custom_prefix_is_found_because_the_device_is_named_by_what_it_publishes(self):
        renamed = {
            k.replace(PREFIX, "garage_charger"): v for k, v in _charger_only().items()
        }
        charger = _found(renamed)
        assert charger.charge_mode_entity == "select.garage_charger_charging_mode"

    def test_the_serial_falls_back_to_the_end_of_the_prefix(self):
        states = _charger_only()
        del states[f"sensor.{PREFIX}_serial_number"]
        assert _found(states).serial == "EV1234A567"

    def test_absent_nothing_is_found(self):
        assert discover_ev_chargers(fixtures.states("hybrid_gen3_two_batteries_3_6_3")) == []

    def test_a_charger_beside_the_inverter_is_found_and_the_inverter_is_not_a_charger(self):
        found = discover_ev_chargers(fixtures.states("hybrid_with_ev_charger_3_6_3"))
        assert [c.brand for c in found] == [EVChargerBrand.GIVENERGY]

    def test_added_later_the_charger_appears_on_the_next_scan(self):
        states = fixtures.states("hybrid_gen3_two_batteries_3_6_3")
        assert discover_ev_chargers(states) == []
        states.update(_charger_only())
        assert [c.brand for c in discover_ev_chargers(states)] == [EVChargerBrand.GIVENERGY]

    def test_a_charging_state_with_no_connection_status_is_not_a_charger(self):
        states = {f"sensor.{PREFIX}_charging_state": SimpleNamespace(state="Idle", attributes={})}
        assert discover_ev_chargers(states) == []

    def test_one_that_appears_without_its_mode_select_gets_it_when_that_appears(self):
        states = _charger_only()
        select = states.pop(f"select.{PREFIX}_charging_mode")
        early = _found(states)
        assert early.charge_mode_entity is None
        states[f"select.{PREFIX}_charging_mode"] = select
        assert early.fill_missing_entities(_found(states)) == ["charge_mode_entity"]


class TestStates:
    @pytest.mark.parametrize(
        ("connection", "state", "expected"),
        [
            ("Not Connected", "Idle", EVChargerState.DISCONNECTED),
            ("Not Connected", "Unknown", EVChargerState.DISCONNECTED),
            ("Connected", "Connected", EVChargerState.CONNECTED),
            ("Connected", "Idle", EVChargerState.CONNECTED),
            ("Connected", "Starting", EVChargerState.CONNECTED),
            ("Connected", "Scheduled", EVChargerState.CONNECTED),
            ("Connected", "Charging", EVChargerState.CHARGING),
            ("Connected", "End of Charging", EVChargerState.COMPLETED),
            ("Connected", "Startup Failure", EVChargerState.CONNECTED),
            ("Connected", "System Failure", EVChargerState.CONNECTED),
            ("Connected", "Unstable CP", EVChargerState.CONNECTED),
            ("Connected", "Updating", EVChargerState.CONNECTED),
            ("Connected", "Unknown", EVChargerState.CONNECTED),
        ],
    )
    def test_every_string_gives_a_normalised_state(self, connection, state, expected):
        charger = _found(_charger_only())
        values = {
            f"sensor.{PREFIX}_connection_status": connection,
            f"sensor.{PREFIX}_charging_state": state,
            f"sensor.{PREFIX}_active_power": "1380",
        }
        states = {k: SimpleNamespace(state=v, attributes={}) for k, v in values.items()}

        update_charger_state(states.get, charger, battery_power_w=0.0)

        assert charger.state is expected

    def test_a_car_that_is_charging_in_name_only_does_not_count_as_active(self):
        charger = _found(_charger_only())
        states = {
            f"sensor.{PREFIX}_connection_status": SimpleNamespace(state="Connected", attributes={}),
            f"sensor.{PREFIX}_charging_state": SimpleNamespace(state="Charging", attributes={}),
            f"sensor.{PREFIX}_active_power": SimpleNamespace(state="0", attributes={}),
        }
        update_charger_state(states.get, charger, battery_power_w=0.0)
        assert not charger.is_active

    def test_power_and_session_energy_are_read(self):
        charger = _found(fixtures.states("hybrid_with_ev_charger_3_6_3"))
        update_charger_state(fixtures.states("hybrid_with_ev_charger_3_6_3").get, charger, 0.0)
        assert charger.power_w == 1380
        assert charger.session_kwh == pytest.approx(2.4)
        assert charger.charge_mode == "Solar"
        assert charger.charge_mode_options == ("Grid", "Solar", "Hybrid")


class TestThePickRule:
    @pytest.mark.parametrize(
        ("options", "expected"),
        [
            (["Grid", "Solar", "Hybrid"], "Solar"),
            (["Fast", "Eco", "Eco+", "Stopped"], "Eco+"),
            (["Grid", "Hybrid"], None),
            (["Stop", "Fast", "Boost", "Pause", "Off", "Max"], None),
            ([], None),
            (["solar"], "solar"),
            (["Surplus"], "Surplus"),
            (["Green"], "Green"),
            (["Solar offset"], None),  # holds "off"
            (["Max solar"], None),  # holds "max"
        ],
    )
    def test_the_table(self, options, expected):
        assert pick_surplus_mode(options) == expected

    def test_an_option_with_a_forbidden_word_is_never_picked_whatever_else_it_says(self):
        for word, name in itertools.product(FORBIDDEN_MODE_WORDS, ("eco+", "solar", "surplus", "green")):
            assert pick_surplus_mode([f"{name} {word}", f"{word} {name}"]) is None, (word, name)

    def test_hybrid_is_never_chosen_automatically(self):
        assert pick_surplus_mode(["Hybrid"]) is None
        assert "hybrid" in FORBIDDEN_MODE_WORDS

    def test_grid_and_stop_are_forbidden(self):
        assert {"grid", "stop", "off", "pause", "fast", "boost", "max"} <= set(FORBIDDEN_MODE_WORDS)

    def test_the_brand_defaults_are_themselves_allowed(self):
        for brand, name in SURPLUS_MODE_DEFAULTS.items():
            assert pick_surplus_mode([name]) == name, brand


class TestTheDecision:
    def _charger(self, mode: str, options=("Grid", "Solar", "Hybrid"), *, plugged=True):
        charger = _found(_charger_only())
        charger.state = EVChargerState.CONNECTED if plugged else EVChargerState.DISCONNECTED
        charger.charge_mode = mode
        charger.charge_mode_options = options
        return charger

    def test_with_surplus_and_a_plugged_in_car_it_selects_solar(self):
        target, reason = decide_ev_charger_action(self._charger("Grid"), 60.0, 3000.0)
        assert target == "Solar"
        assert "switching to Solar" in reason

    def test_already_in_solar_nothing_is_sent(self):
        target, reason = decide_ev_charger_action(self._charger("Solar"), 60.0, 3000.0)
        assert target is None and "Already in Solar" in reason

    def test_a_hybrid_charger_is_moved_to_solar_not_left_drawing_6_amps_from_the_grid(self):
        assert decide_ev_charger_action(self._charger("Hybrid"), 60.0, 3000.0)[0] == "Solar"

    def test_without_surplus_nothing_is_sent(self):
        assert decide_ev_charger_action(self._charger("Grid"), 60.0, 200.0)[0] is None

    def test_no_car_nothing_is_sent(self):
        assert decide_ev_charger_action(self._charger("Grid", plugged=False), 60.0, 3000.0)[0] is None

    def test_a_select_with_no_surplus_option_is_left_alone_and_says_so(self):
        charger = self._charger("Grid", options=("Grid", "Hybrid"))
        target, reason = decide_ev_charger_action(charger, 60.0, 3000.0)
        assert target is None and "no surplus-only mode" in reason

    def test_options_not_read_yet_use_the_brand_name(self):
        assert decide_ev_charger_action(self._charger("Grid", options=None), 60.0, 3000.0)[0] == "Solar"

    @pytest.mark.parametrize("mode", ["Grid", "Solar", "Hybrid", "", None])
    @pytest.mark.parametrize("surplus", [0.0, 1000.0, 1380.0, 5000.0])
    @pytest.mark.parametrize("soc", [0.0, 50.0, 100.0])
    @pytest.mark.parametrize("plugged", [True, False])
    def test_it_never_selects_grid_hybrid_or_a_stop(self, mode, surplus, soc, plugged):
        target, _ = decide_ev_charger_action(self._charger(mode, plugged=plugged), soc, surplus)
        assert target in (None, "Solar")

    def test_a_zappi_is_unchanged(self):
        zappi = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi 1",
            serial="1",
            display_name="Zappi (1)",
            charge_mode_entity="select.myenergi_zappi_1_charge_mode",
            state=EVChargerState.CONNECTED,
            charge_mode="Fast",
        )
        assert decide_ev_charger_action(zappi, 60.0, 3000.0)[0] == "Eco+"
        zappi.charge_mode_options = ("Fast", "Eco", "Eco+", "Stopped")
        assert decide_ev_charger_action(zappi, 60.0, 3000.0)[0] == "Eco+"
