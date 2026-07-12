"""
test_givtcp.py — Unit tests for discovery/givtcp.py.

All tests are HA-free: the discovery functions accept a plain dict of
{entity_id: state_object} rather than hass.states.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _State:
    state: str


def _states(*entity_ids: str, extra: dict | None = None) -> dict:
    """Build a minimal all_states dict from a list of entity_id strings."""
    result = {eid: _State(state="ok") for eid in entity_ids}
    if extra:
        result.update(extra)
    return result


def _serial_entity(prefix: str, serial: str = "ABC123") -> dict:
    """Return a states dict that has the GivTCP serial sensor."""
    eid = f"sensor.{prefix}_invertor_serial_number"
    return {eid: _State(state=serial)}


# ── discover_givtcp_inverters ─────────────────────────────────────────────────


class TestDiscoverGivTCPInverters:
    def test_empty_states_returns_no_inverters(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        assert discover_givtcp_inverters({}) == []

    def test_discovers_inverter_from_serial_sensor(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_ABC123", serial="ABC123")
        inverters = discover_givtcp_inverters(states)
        assert len(inverters) == 1
        assert inverters[0].serial == "ABC123"

    def test_uses_prefix_as_serial_when_state_unavailable(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = {"sensor.givtcp_XYZ_invertor_serial_number": _State(state="unavailable")}
        inverters = discover_givtcp_inverters(states)
        assert len(inverters) == 1
        assert inverters[0].serial == "givtcp_XYZ"

    def test_discovers_battery_soc_v3(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_SN1")
        states["sensor.givtcp_SN1_soc"] = _State(state="75")
        inverters = discover_givtcp_inverters(states)
        assert inverters[0].entities.get("battery_soc") == "sensor.givtcp_SN1_soc"

    def test_falls_back_to_v2_battery_soc(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_SN2")
        states["sensor.givtcp_SN2_battery_soc"] = _State(state="60")
        inverters = discover_givtcp_inverters(states)
        assert inverters[0].entities.get("battery_soc") == "sensor.givtcp_SN2_battery_soc"

    def test_reads_battery_capacity_from_sensor_state(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_SN3")
        states["sensor.givtcp_SN3_battery_capacity_kwh"] = _State(state="9.5")
        inverters = discover_givtcp_inverters(states)
        assert inverters[0].battery_capacity_kwh == 9.5

    def test_ignores_unavailable_battery_capacity(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_SN4")
        states["sensor.givtcp_SN4_battery_capacity_kwh"] = _State(state="unavailable")
        inverters = discover_givtcp_inverters(states)
        assert inverters[0].battery_capacity_kwh is None

    def test_multiple_inverters_sorted_by_serial(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = {
            "sensor.givtcp_ZZZ_invertor_serial_number": _State(state="ZZZ"),
            "sensor.givtcp_AAA_invertor_serial_number": _State(state="AAA"),
        }
        inverters = discover_givtcp_inverters(states)
        assert [inv.serial for inv in inverters] == ["AAA", "ZZZ"]

    def test_missing_entity_recorded(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            discover_givtcp_inverters,
        )

        states = _serial_entity("givtcp_SN5")
        inverters = discover_givtcp_inverters(states)
        assert len(inverters[0].missing_entities) > 0


# ── GivTCPInverter properties ─────────────────────────────────────────────────


class TestGivTCPInverterProperties:
    def _full_inverter(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            GivTCPInverter,
        )

        inv = GivTCPInverter(serial="SN", prefix="givtcp_SN", display_name="GivTCP SN")
        inv.entities = {
            "solar_power": "sensor.givtcp_SN_pv_power",
            "battery_soc": "sensor.givtcp_SN_soc",
            "battery_power": "sensor.givtcp_SN_battery_power",
            "grid_power": "sensor.givtcp_SN_grid_power",
            "house_load": "sensor.givtcp_SN_load_power",
            "target_soc": "number.givtcp_SN_target_soc",
            "enable_charge_target": "switch.givtcp_SN_enable_charge_target",
            "enable_charge_schedule": "switch.givtcp_SN_enable_charge_schedule",
            "charge_start_time": "select.givtcp_SN_charge_start_time_slot_1",
            "charge_end_time": "select.givtcp_SN_charge_end_time_slot_1",
        }
        return inv

    def test_is_fully_configured_true_when_all_power_sensors_present(self):
        inv = self._full_inverter()
        assert inv.is_fully_configured is True

    def test_is_fully_configured_false_when_missing_sensor(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import GivTCPInverter

        inv = GivTCPInverter(serial="SN", prefix="givtcp_SN", display_name="GivTCP SN")
        inv.entities = {"solar_power": "sensor.givtcp_SN_pv_power"}
        assert inv.is_fully_configured is False

    def test_has_charge_scheduling_true_when_all_present(self):
        inv = self._full_inverter()
        assert inv.has_charge_scheduling is True

    def test_has_charge_scheduling_false_when_missing_entity(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import GivTCPInverter

        inv = GivTCPInverter(serial="SN", prefix="givtcp_SN", display_name="GivTCP SN")
        inv.entities = {"target_soc": "number.givtcp_SN_target_soc"}
        assert inv.has_charge_scheduling is False


# ── get_suggested_entities ────────────────────────────────────────────────────


class TestGetSuggestedEntities:
    def test_returns_entities_dict(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            GivTCPInverter,
            get_suggested_entities,
        )

        inv = GivTCPInverter(serial="SN", prefix="givtcp_SN", display_name="GivTCP SN")
        inv.entities = {"solar_power": "sensor.givtcp_SN_pv_power"}
        result = get_suggested_entities(inv)
        assert result == {"solar_power": "sensor.givtcp_SN_pv_power"}

    def test_returns_copy_not_reference(self):
        from custom_components.givenergy_inverter_manager.discovery.givtcp import (
            GivTCPInverter,
            get_suggested_entities,
        )

        inv = GivTCPInverter(serial="SN", prefix="givtcp_SN", display_name="GivTCP SN")
        inv.entities = {"solar_power": "sensor.givtcp_SN_pv_power"}
        result = get_suggested_entities(inv)
        result["extra"] = "injected"
        assert "extra" not in inv.entities
