"""

givtcp.py — GivTCP inverter auto-discovery for GivEnergy Inverter Manager.

Supports both GivTCP v2 (battery_soc suffix) and v3 (soc suffix).
Also auto-reads battery capacity from the inverter's capacity sensor.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

SERIAL_SENSOR_SUFFIX = "_invertor_serial_number"
GIVTCP_PREFIX = "givtcp_"

ENTITY_SUFFIXES: dict[str, str] = {
    "solar_power": "_pv_power",
    # battery_soc handled specially: GivTCP v3 uses _soc, v2 uses _battery_soc
    "battery_power": "_battery_power",
    "grid_power": "_grid_power",
    "house_load": "_load_power",
    "inverter_temp": "_invertor_temperature",  # GivTCP spells it "invertor"
    "target_soc": "_target_soc",
    "enable_charge_target": "_enable_charge_target",
    "enable_charge_schedule": "_enable_charge_schedule",
    "charge_start_time": "_charge_start_time_slot_1",
    "charge_end_time": "_charge_end_time_slot_1",
    "battery_capacity_kwh": "_battery_capacity_kwh",
}

ENTITY_DOMAINS: dict[str, str] = {
    "solar_power": "sensor",
    "battery_soc": "sensor",
    "battery_power": "sensor",
    "grid_power": "sensor",
    "house_load": "sensor",
    "target_soc": "number",
    "enable_charge_target": "switch",
    "enable_charge_schedule": "switch",
    "charge_start_time": "select",
    "charge_end_time": "select",
    "battery_capacity_kwh": "sensor",
    "inverter_temp": "sensor",
}


@dataclass
class GivTCPInverter:
    """Represents a discovered GivTCP inverter and its associated entities."""

    serial: str
    prefix: str
    display_name: str
    entities: dict[str, str] = field(default_factory=dict)
    missing_entities: list[str] = field(default_factory=list)
    battery_capacity_kwh: float | None = None  # read from sensor state at discovery time

    @property
    def is_fully_configured(self) -> bool:
        """True if all five required power sensors are present."""
        required = {"solar_power", "battery_soc", "battery_power", "grid_power", "house_load"}
        return required.issubset(self.entities.keys())

    @property
    def has_charge_scheduling(self) -> bool:
        """True if all five charge scheduling entities are present."""
        scheduling = {
            "target_soc",
            "enable_charge_target",
            "enable_charge_schedule",
            "charge_start_time",
            "charge_end_time",
        }
        return scheduling.issubset(self.entities.keys())


def discover_givtcp_inverters(all_states: dict) -> list[GivTCPInverter]:
    """
    Scan HA entity states for GivTCP inverters.

    Accepts a dict of {entity_id: state_object} — HA-free and testable.
    Returns a list of discovered inverters sorted by serial number.
    Handles both GivTCP v2 (_battery_soc suffix) and v3 (_soc suffix).
    """
    inverters: list[GivTCPInverter] = []

    for entity_id, state in all_states.items():
        if GIVTCP_PREFIX not in entity_id:
            continue
        if not entity_id.endswith(SERIAL_SENSOR_SUFFIX):
            continue

        without_domain = entity_id.split(".", 1)[1]
        prefix = without_domain[: -len(SERIAL_SENSOR_SUFFIX)]
        serial = state.state if state.state not in ("unavailable", "unknown", "") else prefix

        inverter = GivTCPInverter(serial=serial, prefix=prefix, display_name=f"GivTCP {serial}")

        # ── Battery SoC: try GivTCP v3 name first, fall back to v2 ──────────
        for soc_suffix in ("_soc", "_battery_soc"):
            candidate = f"sensor.{prefix}{soc_suffix}"
            if candidate in all_states:
                inverter.entities["battery_soc"] = candidate
                break
        else:
            inverter.missing_entities.append(f"sensor.{prefix}_soc")

        # ── All other entities ────────────────────────────────────────────────
        for key, suffix in ENTITY_SUFFIXES.items():
            domain = ENTITY_DOMAINS.get(key, "sensor")
            candidate = f"{domain}.{prefix}{suffix}"
            if candidate in all_states:
                inverter.entities[key] = candidate
            else:
                inverter.missing_entities.append(candidate)

        # ── Read battery capacity value from sensor state ────────────────────
        cap_eid = inverter.entities.get("battery_capacity_kwh")
        if cap_eid:
            cap_state = all_states.get(cap_eid)
            if cap_state and cap_state.state not in ("unavailable", "unknown", ""):
                with contextlib.suppress(ValueError, TypeError):
                    inverter.battery_capacity_kwh = float(cap_state.state)

        inverters.append(inverter)

    inverters.sort(key=lambda i: i.serial)
    return inverters


def get_suggested_entities(inverter: GivTCPInverter) -> dict[str, str]:
    """Return config key → entity_id dict for all discovered entities."""
    return dict(inverter.entities)
