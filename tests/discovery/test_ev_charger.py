"""
test_ev_charger.py — Unit tests for multi-brand EV charger discovery and battery protection.

Tests EVCharger state normalisation, brand-specific entity discovery patterns,
battery drain detection, and the battery protection decision logic — all without
requiring a running Home Assistant instance.
"""

import pytest

from custom_components.givenergy_inverter_manager.core.rules import (
    decide_ev_charger_action,
    should_protect_battery_from_charger,
)
from custom_components.givenergy_inverter_manager.discovery import (
    ZAPPI_BATTERY_DRAINING_MODES,
    ZAPPI_ECO_PLUS_MODE,
    ZAPPI_STOPPED_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    discover_ev_chargers,
    update_charger_state,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeState:
    def __init__(self, entity_id: str, state: str):
        self.entity_id = entity_id
        self.state = state


def _states(entity_states: dict[str, str]) -> dict:
    """Build a {entity_id: state_object} dict for use with discover_ev_chargers."""
    return {eid: _FakeState(eid, val) for eid, val in entity_states.items()}


def _get_state(entity_states: dict[str, str]):
    """Return a get_state callable for use with update_charger_state."""
    state_map = {eid: _FakeState(eid, val) for eid, val in entity_states.items()}
    return lambda eid: state_map.get(eid)


def _make_zappi(serial="12345678", mode="Eco+") -> EVCharger:
    return EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name=f"Zappi {serial}",
        serial=serial,
        display_name=f"Zappi ({serial})",
        status_entity=f"sensor.myenergi_zappi_{serial}_plug_status",
        power_entity=f"sensor.myenergi_zappi_{serial}_internal_load_ct1",
        session_energy_entity=f"sensor.myenergi_zappi_{serial}_charge_added_session",
        charge_mode_entity=f"select.myenergi_zappi_{serial}_charge_mode",
        charge_mode=mode,
    )


# ── EVCharger state normalisation ─────────────────────────────────────────────


class TestEVChargerStateNormalisation:
    def test_zappi_ev_disconnected(self):
        ch = _make_zappi()
        assert ch.normalise_state("EV Disconnected") == EVChargerState.DISCONNECTED

    def test_zappi_ev_connected(self):
        ch = _make_zappi()
        assert ch.normalise_state("EV Connected") == EVChargerState.CONNECTED

    def test_zappi_waiting(self):
        ch = _make_zappi()
        assert ch.normalise_state("Waiting for EV") == EVChargerState.CONNECTED

    def test_zappi_charging(self):
        ch = _make_zappi()
        assert ch.normalise_state("Charging") == EVChargerState.CHARGING

    def test_zappi_boosting(self):
        ch = _make_zappi()
        assert ch.normalise_state("Boosting") == EVChargerState.BOOSTING

    def test_zappi_paused(self):
        ch = _make_zappi()
        assert ch.normalise_state("Paused") == EVChargerState.PAUSED

    def test_zappi_completed(self):
        ch = _make_zappi()
        assert ch.normalise_state("Completed") == EVChargerState.COMPLETED

    def test_zappi_case_insensitive(self):
        ch = _make_zappi()
        assert ch.normalise_state("EV DISCONNECTED") == EVChargerState.DISCONNECTED
        assert ch.normalise_state("charging") == EVChargerState.CHARGING

    def test_wallbox_charging(self):
        ch = EVCharger(brand=EVChargerBrand.WALLBOX, name="wb", serial="x", display_name="wb")
        assert ch.normalise_state("Charging") == EVChargerState.CHARGING

    def test_ocpp_available(self):
        ch = EVCharger(brand=EVChargerBrand.OCPP, name="oc", serial="x", display_name="oc")
        assert ch.normalise_state("Available") == EVChargerState.DISCONNECTED

    def test_ocpp_suspendedev(self):
        ch = EVCharger(brand=EVChargerBrand.OCPP, name="oc", serial="x", display_name="oc")
        assert ch.normalise_state("SuspendedEV") == EVChargerState.PAUSED

    def test_unknown_state(self):
        ch = _make_zappi()
        assert ch.normalise_state("some_unknown_state") == EVChargerState.UNKNOWN

    def test_is_active_when_charging(self):
        ch = _make_zappi()
        ch.state = EVChargerState.CHARGING
        assert ch.is_active is True

    def test_is_active_when_boosting(self):
        ch = _make_zappi()
        ch.state = EVChargerState.BOOSTING
        assert ch.is_active is True

    def test_not_active_when_paused(self):
        ch = _make_zappi()
        ch.state = EVChargerState.PAUSED
        assert ch.is_active is False

    def test_is_plugged_in(self):
        ch = _make_zappi()
        ch.state = EVChargerState.CHARGING
        assert ch.is_plugged_in is True

    def test_not_plugged_in(self):
        ch = _make_zappi()
        ch.state = EVChargerState.DISCONNECTED
        assert ch.is_plugged_in is False

    def test_can_set_solar_only_zappi(self):
        ch = _make_zappi()
        assert ch.can_set_solar_only_mode is True

    def test_cannot_set_solar_only_wallbox(self):
        ch = EVCharger(brand=EVChargerBrand.WALLBOX, name="wb", serial="x", display_name="wb")
        assert ch.can_set_solar_only_mode is False


# ── Discovery ─────────────────────────────────────────────────────────────────


class TestDiscoverEVChargers:
    def test_discovers_zappi(self):
        all_states = _states(
            {
                "sensor.myenergi_zappi_12345678_plug_status": "EV Disconnected",
                "sensor.myenergi_zappi_12345678_internal_load_ct1": "0",
                "sensor.myenergi_zappi_12345678_charge_added_session": "0.0",
                "select.myenergi_zappi_12345678_charge_mode": "Eco+",
            }
        )
        result = discover_ev_chargers(all_states)
        assert len(result) == 1
        assert result[0].brand == EVChargerBrand.ZAPPI
        assert result[0].serial == "12345678"
        assert result[0].power_entity == "sensor.myenergi_zappi_12345678_internal_load_ct1"
        assert result[0].charge_mode_entity == "select.myenergi_zappi_12345678_charge_mode"

    def test_discovers_wallbox(self):
        all_states = _states(
            {
                "sensor.wallbox_pulsar_status_description": "Charging",
                "sensor.wallbox_pulsar_charging_power": "7000",
            }
        )
        result = discover_ev_chargers(all_states)
        assert any(c.brand == EVChargerBrand.WALLBOX for c in result)

    def test_discovers_ocpp(self):
        all_states = _states(
            {
                "sensor.ocpp_charger1_status_connector": "Charging",
            }
        )
        result = discover_ev_chargers(all_states)
        assert any(c.brand == EVChargerBrand.OCPP for c in result)

    def test_discovers_ohme(self):
        all_states = _states(
            {
                "sensor.ohme_home_pro_status": "Charging",
            }
        )
        result = discover_ev_chargers(all_states)
        assert any(c.brand == EVChargerBrand.OHME for c in result)

    def test_discovers_easee(self):
        all_states = _states(
            {
                "sensor.easee_home_status": "charging",
            }
        )
        result = discover_ev_chargers(all_states)
        assert any(c.brand == EVChargerBrand.EASEE for c in result)

    def test_no_chargers_when_none_present(self):
        all_states = _states({"sensor.some_other_thing": "on"})
        result = discover_ev_chargers(all_states)
        assert result == []

    def test_multiple_brands_discovered(self):
        all_states = _states(
            {
                "sensor.myenergi_zappi_111_plug_status": "EV Disconnected",
                "sensor.wallbox_home_status_description": "Waiting",
            }
        )
        result = discover_ev_chargers(all_states)
        assert len(result) == 2

    def test_sorted_by_brand_then_serial(self):
        all_states = _states(
            {
                "sensor.myenergi_zappi_zzz_plug_status": "EV Disconnected",
                "sensor.myenergi_zappi_aaa_plug_status": "EV Disconnected",
            }
        )
        result = discover_ev_chargers(all_states)
        assert result[0].serial < result[1].serial


# ── Update charger state ──────────────────────────────────────────────────────


class TestUpdateChargerState:
    def test_state_updated_from_entity(self):
        ch = _make_zappi("99")
        all_states = _states(
            {
                "sensor.myenergi_zappi_99_plug_status": "Charging",
                "sensor.myenergi_zappi_99_internal_load_ct1": "6500",
                "sensor.myenergi_zappi_99_charge_added_session": "12.5",
                "select.myenergi_zappi_99_charge_mode": "Fast",
            }
        )
        update_charger_state(all_states.get, ch, battery_power_w=0)
        assert ch.state == EVChargerState.CHARGING
        assert ch.power_w == pytest.approx(6500)
        assert ch.session_kwh == pytest.approx(12.5)
        assert ch.charge_mode == "Fast"

    def test_battery_drain_detected_when_charging_and_battery_discharging(self):
        ch = _make_zappi("99")
        ch.state = EVChargerState.CHARGING
        all_states = _states(
            {
                "sensor.myenergi_zappi_99_plug_status": "Charging",
                "sensor.myenergi_zappi_99_internal_load_ct1": "5000",
                "sensor.myenergi_zappi_99_charge_added_session": "5.0",
                "select.myenergi_zappi_99_charge_mode": "Fast",
            }
        )
        # battery_power_w = -3000 means battery is discharging at 3kW
        update_charger_state(all_states.get, ch, battery_power_w=-3000)
        assert ch.is_draining_battery is True

    def test_no_battery_drain_when_battery_charging(self):
        ch = _make_zappi("99")
        all_states = _states(
            {
                "sensor.myenergi_zappi_99_plug_status": "Charging",
                "sensor.myenergi_zappi_99_internal_load_ct1": "5000",
                "sensor.myenergi_zappi_99_charge_added_session": "5.0",
                "select.myenergi_zappi_99_charge_mode": "Fast",
            }
        )
        # battery_power_w = +2000 means battery is charging
        update_charger_state(all_states.get, ch, battery_power_w=2000)
        assert ch.is_draining_battery is False

    def test_no_battery_drain_when_charger_not_active(self):
        ch = _make_zappi("99")
        all_states = _states(
            {
                "sensor.myenergi_zappi_99_plug_status": "EV Disconnected",
                "sensor.myenergi_zappi_99_internal_load_ct1": "0",
                "sensor.myenergi_zappi_99_charge_added_session": "0",
                "select.myenergi_zappi_99_charge_mode": "Eco+",
            }
        )
        update_charger_state(all_states.get, ch, battery_power_w=-3000)
        assert ch.is_draining_battery is False

    def test_unavailable_state_does_not_crash(self):
        ch = _make_zappi("99")
        all_states = _states(
            {
                "sensor.myenergi_zappi_99_plug_status": "unavailable",
            }
        )
        update_charger_state(all_states.get, ch, battery_power_w=0)
        assert ch.state == EVChargerState.UNKNOWN


# ── Battery protection ────────────────────────────────────────────────────────


class TestShouldProtectBatteryFromCharger:
    def test_protect_when_zappi_fast_draining_low_battery(self):
        ch = _make_zappi(mode="Fast")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = True
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=15.0, battery_protection_threshold=20.0
        )
        assert should is True
        # Reason should mention the mode and the SoC threshold
        assert "Fast" in reason
        assert "15" in reason

    def test_protect_when_zappi_eco_draining_low_battery(self):
        ch = _make_zappi(mode="Eco")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = True
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=10.0, battery_protection_threshold=20.0
        )
        assert should is True

    def test_no_protect_when_zappi_eco_plus(self):
        """Eco+ only charges from solar — no battery risk."""
        ch = _make_zappi(mode="Eco+")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = False  # Eco+ won't drain battery
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=15.0, battery_protection_threshold=20.0
        )
        assert should is False

    def test_no_protect_when_battery_high(self):
        """Battery above threshold — OK to let charger draw from it."""
        ch = _make_zappi(mode="Fast")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = True
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=80.0, battery_protection_threshold=20.0
        )
        assert should is False

    def test_no_protect_when_not_charging(self):
        ch = _make_zappi(mode="Fast")
        ch.state = EVChargerState.DISCONNECTED
        ch.is_draining_battery = False
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=10.0, battery_protection_threshold=20.0
        )
        assert should is False

    def test_no_protect_when_not_draining(self):
        """Charging but from solar/grid — no battery drain."""
        ch = _make_zappi(mode="Fast")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = False
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=10.0, battery_protection_threshold=20.0
        )
        assert should is False

    def test_reason_string_always_returned(self):
        ch = _make_zappi(mode="Fast")
        ch.state = EVChargerState.CHARGING
        ch.is_draining_battery = True
        _, reason = should_protect_battery_from_charger(
            ch, battery_soc=10.0, battery_protection_threshold=20.0
        )
        assert isinstance(reason, str) and len(reason) > 0

    def test_zappi_battery_draining_modes_are_correct(self):
        """Verify the modes that can drain the battery are correctly listed."""
        assert "fast" in ZAPPI_BATTERY_DRAINING_MODES
        assert "eco" in ZAPPI_BATTERY_DRAINING_MODES
        assert "eco+" not in ZAPPI_BATTERY_DRAINING_MODES
        assert "stopped" not in ZAPPI_BATTERY_DRAINING_MODES


# ── decide_ev_charger_action ──────────────────────────────────────────────────


class TestDecideEVChargerAction:
    def _zappi(self, mode="Eco+", state=EVChargerState.CONNECTED) -> EVCharger:
        ch = _make_zappi(mode=mode)
        ch.state = state
        return ch

    def test_stops_when_battery_below_threshold(self):
        ch = self._zappi(mode="Fast", state=EVChargerState.CHARGING)
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=15.0,
            battery_power_w=-2000,
            solar_surplus_w=0,
            protection_threshold=20.0,
        )
        assert target == ZAPPI_STOPPED_MODE
        assert "15" in reason

    def test_no_action_already_stopped_at_low_soc(self):
        ch = self._zappi(mode="Stopped", state=EVChargerState.PAUSED)
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=15.0,
            battery_power_w=0,
            solar_surplus_w=0,
            protection_threshold=20.0,
        )
        assert target is None  # already stopped, no change needed

    def test_sets_eco_plus_when_battery_ok_and_surplus(self):
        ch = self._zappi(mode="Fast", state=EVChargerState.CHARGING)
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=85.0,
            battery_power_w=500,
            solar_surplus_w=2000,
            protection_threshold=20.0,
        )
        assert target == ZAPPI_ECO_PLUS_MODE
        assert "surplus" in reason.lower()

    def test_no_action_already_eco_plus_with_surplus(self):
        ch = self._zappi(mode="Eco+", state=EVChargerState.CHARGING)
        target, _ = decide_ev_charger_action(
            ch,
            battery_soc=85.0,
            battery_power_w=500,
            solar_surplus_w=2000,
            protection_threshold=20.0,
        )
        assert target is None  # already in right mode

    def test_no_action_when_not_plugged_in(self):
        ch = self._zappi(mode="Fast", state=EVChargerState.DISCONNECTED)
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=10.0,
            battery_power_w=-2000,
            solar_surplus_w=0,
            protection_threshold=20.0,
        )
        assert target is None
        assert "not connected" in reason.lower()

    def test_no_action_battery_ok_no_surplus(self):
        """Battery is fine but no surplus — leave mode as-is."""
        ch = self._zappi(mode="Eco+", state=EVChargerState.CONNECTED)
        target, _ = decide_ev_charger_action(
            ch,
            battery_soc=80.0,
            battery_power_w=0,
            solar_surplus_w=200,
            protection_threshold=20.0,
        )
        assert target is None

    def test_non_zappi_no_mode_change(self):
        """Non-Zappi chargers can't be mode-switched, target is always None."""
        ch = EVCharger(
            brand=EVChargerBrand.WALLBOX,
            name="wb",
            serial="x",
            display_name="wb",
            state=EVChargerState.CHARGING,
        )
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=10.0,
            battery_power_w=-2000,
            solar_surplus_w=0,
            protection_threshold=20.0,
        )
        assert target is None
        assert "manual" in reason.lower()


# ── Currency constants ────────────────────────────────────────────────────────


class TestCurrencyConstants:
    def test_currencies_dict_has_eur(self):
        from custom_components.givenergy_inverter_manager.const import CURRENCIES

        assert "EUR" in CURRENCIES
        assert CURRENCIES["EUR"] == "€"

    def test_currencies_dict_has_gbp(self):
        from custom_components.givenergy_inverter_manager.const import CURRENCIES

        assert "GBP" in CURRENCIES
        assert CURRENCIES["GBP"] == "£"

    def test_default_currency_is_eur(self):
        from custom_components.givenergy_inverter_manager.const import DEFAULT_CURRENCY

        assert DEFAULT_CURRENCY == "EUR"

    def test_all_currencies_have_symbol(self):
        from custom_components.givenergy_inverter_manager.const import CURRENCIES

        for code, symbol in CURRENCIES.items():
            assert isinstance(symbol, str) and len(symbol) >= 1, (
                f"Currency {code} has invalid symbol {symbol!r}"
            )


class TestEVChargerAdditionalCoverage:
    def test_can_be_paused_with_mode_entity(self):
        """can_be_paused is True when charge_mode_entity is set."""
        ch = _make_zappi()
        assert ch.can_be_paused is True

    def test_can_be_paused_without_mode_entity(self):
        ch = EVCharger(brand=EVChargerBrand.WALLBOX, name="wb", serial="x", display_name="wb")
        assert ch.can_be_paused is False

    def test_non_zappi_non_draining_protect_returns_false(self):
        """Non-Zappi charger draining battery without mode select returns True but no Zappi logic."""
        ch = EVCharger(
            brand=EVChargerBrand.WALLBOX,
            name="wb",
            serial="x",
            display_name="wb",
            state=EVChargerState.CHARGING,
        )
        ch.is_draining_battery = True
        should, reason = should_protect_battery_from_charger(
            ch, battery_soc=10.0, battery_protection_threshold=20.0
        )
        assert should is True
        assert "EV charger" in reason

    def test_ohme_current_entity_skipped_in_discovery(self):
        """Ohme sensor with 'current_' in name should not be discovered as a charger."""
        all_states = _states(
            {
                "sensor.ohme_home_pro_current_draw": "10",  # should be skipped
            }
        )
        result = discover_ev_chargers(all_states)
        assert not any(c.brand == EVChargerBrand.OHME for c in result)

    def test_update_charger_non_numeric_power_defaults_zero(self):
        """If power entity returns non-numeric state, power_w defaults to 0."""
        ch = _make_zappi("77")
        all_states = _states(
            {
                "sensor.myenergi_zappi_77_plug_status": "Charging",
                "sensor.myenergi_zappi_77_internal_load_ct1": "not_a_number",
                "sensor.myenergi_zappi_77_charge_added_session": "5.0",
                "select.myenergi_zappi_77_charge_mode": "Fast",
            }
        )
        update_charger_state(all_states.get, ch, battery_power_w=0)
        assert ch.power_w == 0.0


class TestEVPowerEntityWarning:
    """EV charger discovery must warn and return the charger when power entity is missing."""

    def _zappi_states_without_power(self, serial: str = "12345678") -> dict:
        """States with a Zappi plug_status but no power entity."""
        from unittest.mock import MagicMock

        state = MagicMock()
        state.state = "Connected"
        return {f"sensor.myenergi_zappi_{serial}_plug_status": state}

    def test_warning_emitted_when_power_entity_missing(self, caplog):
        """_discover_zappi must log a warning when the power entity is not in states."""
        import logging

        from custom_components.givenergy_inverter_manager.discovery.ev_charger import (
            _discover_zappi,
        )

        with caplog.at_level(
            logging.WARNING,
            logger="custom_components.givenergy_inverter_manager.discovery.ev_charger",
        ):
            _discover_zappi(self._zappi_states_without_power())
        assert any("power entity not found" in r.message for r in caplog.records), (
            "Must warn when Zappi is discovered but power entity is absent — "
            "without this EV kWh silently reads 0 with no diagnostic."
        )

    def test_charger_still_returned_when_power_entity_missing(self):
        """Charger must still be in the returned list despite missing power entity."""
        from custom_components.givenergy_inverter_manager.discovery.ev_charger import (
            _discover_zappi,
        )

        chargers = _discover_zappi(self._zappi_states_without_power())
        assert len(chargers) == 1, "Charger must be returned even without power entity"
        assert chargers[0].power_entity is None

    def test_no_warning_when_power_entity_present(self, caplog):
        """No warning emitted when all entities are present."""
        import logging
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.discovery.ev_charger import (
            _discover_zappi,
        )

        serial = "12345678"
        mk = MagicMock()
        states = {
            f"sensor.myenergi_zappi_{serial}_plug_status": mk,
            f"sensor.myenergi_zappi_{serial}_internal_load_ct1": mk,
        }
        with caplog.at_level(
            logging.WARNING,
            logger="custom_components.givenergy_inverter_manager.discovery.ev_charger",
        ):
            _discover_zappi(states)
        assert not any("power entity" in r.message for r in caplog.records)


class TestDecideEVChargerActionCheapRate:
    """During cheap rate, Zappi must stop if battery is discharging to power the EV."""

    def _zappi(self, mode="Fast") -> EVCharger:
        ch = _make_zappi(mode=mode)
        ch.state = EVChargerState.CHARGING
        return ch

    def test_stops_zappi_when_cheap_rate_and_battery_discharging(self):
        # Arrange — cheap rate active, battery discharging
        ch = self._zappi(mode="Fast")
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=70.0,
            battery_power_w=-1500,
            solar_surplus_w=0,
            protection_threshold=50.0,
            in_cheap_rate_period=True,
        )
        # Assert
        assert target == ZAPPI_STOPPED_MODE
        assert "cheap rate" in reason.lower()

    def test_no_stop_when_cheap_rate_but_battery_not_discharging(self):
        # Arrange — cheap rate, but battery is idle or charging
        ch = self._zappi(mode="Fast")
        target, _ = decide_ev_charger_action(
            ch,
            battery_soc=70.0,
            battery_power_w=0,
            solar_surplus_w=0,
            protection_threshold=50.0,
            in_cheap_rate_period=True,
        )
        # Assert — battery not being drained, EV can continue
        assert target is None

    def test_no_stop_when_battery_discharging_but_not_cheap_rate(self):
        # Arrange — battery discharging, but NOT in cheap rate (normal day rate)
        ch = self._zappi(mode="Fast")
        target, _ = decide_ev_charger_action(
            ch,
            battery_soc=70.0,
            battery_power_w=-1500,
            solar_surplus_w=0,
            protection_threshold=50.0,
            in_cheap_rate_period=False,
        )
        # Assert — cheap rate guard does not apply; SoC check applies instead
        assert target is None  # 70% > 50% threshold so no stop

    def test_cheap_rate_guard_takes_priority_over_soc_threshold(self):
        # Arrange — battery at 80% (above threshold) but cheap rate + discharging
        ch = self._zappi(mode="Eco+")
        target, reason = decide_ev_charger_action(
            ch,
            battery_soc=80.0,
            battery_power_w=-500,
            solar_surplus_w=0,
            protection_threshold=50.0,
            in_cheap_rate_period=True,
        )
        # Assert — stopped even though SoC is above the daytime threshold
        assert target == ZAPPI_STOPPED_MODE

    def test_already_stopped_during_cheap_rate_no_action(self):
        # Arrange — Zappi already stopped
        ch = _make_zappi(mode="Stopped")
        ch.state = EVChargerState.PAUSED
        target, _ = decide_ev_charger_action(
            ch,
            battery_soc=70.0,
            battery_power_w=-500,
            solar_surplus_w=0,
            protection_threshold=50.0,
            in_cheap_rate_period=True,
        )
        # Assert — already stopped, no change needed
        assert target is None
