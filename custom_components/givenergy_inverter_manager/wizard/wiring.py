"""
wiring.py - the GivTCP entities of one inverter, as the config keys they are stored under.

Setup finds them by discovery and reconfigure lets the user remap them. The five power
entities are required, the other six (inverter temperature and the charge controls) are optional.
The serial is the unique id of the config entry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_MAX_OUTPUT_ENTITY,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)
from ..core.wizard_pages import WIRING_REQUIRED
from ..inverter.givtcp.discovery import GIVTCP_PREFIX, GivTCPInverter, device_prefix, limit_sensors

# discover_givtcp_inverters() entity keys to the config keys they are stored under.
DISCOVERY_TO_CONF: dict[str, str] = {
    "solar_power": CONF_SOLAR_POWER,
    "battery_soc": CONF_BATTERY_SOC,
    "battery_power": CONF_BATTERY_POWER,
    "grid_power": CONF_GRID_POWER,
    "house_load": CONF_HOUSE_LOAD,
    "inverter_temp": CONF_INVERTER_TEMP_ENTITY,
    "target_soc": CONF_TARGET_SOC_ENTITY,
    "enable_charge_target": CONF_ENABLE_CHARGE_TARGET,
    "enable_charge_schedule": CONF_ENABLE_CHARGE_SCHEDULE,
    "charge_start_time": CONF_CHARGE_START_TIME_ENTITY,
    "charge_end_time": CONF_CHARGE_END_TIME_ENTITY,
}

# The six wiring entities that may be left empty.
WIRING_OPTIONAL = (
    CONF_INVERTER_TEMP_ENTITY,
    CONF_TARGET_SOC_ENTITY,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
)
WIRING_KEYS = (*WIRING_REQUIRED, *WIRING_OPTIONAL)

# The serial GivTCP puts in an entity id: sensor.givtcp_<serial>_pv_power.
_ENTITY_SERIAL = re.compile(rf"^[a-z_]+\.{GIVTCP_PREFIX}(?P<serial>[a-z0-9]+)_")
MANUAL_SERIAL = "manual"


def wiring_from(inverter: GivTCPInverter) -> dict[str, str]:
    """The config entries for the entities discovery found on *inverter*."""
    return {
        conf: inverter.entities[found]
        for found, conf in DISCOVERY_TO_CONF.items()
        if found in inverter.entities
    }


def limit_sources_from(inverter: GivTCPInverter) -> dict[str, str]:
    """The sensors capacity and output are read from, for each one that reads a usable number.

    A sensor that is missing or reads nothing is left out, so the typed value stands for it.
    """
    sources: dict[str, str] = {}
    if inverter.battery_capacity_kwh is not None:
        sources[CONF_BATTERY_CAPACITY_ENTITY] = inverter.entities["battery_capacity_kwh"]
    if inverter.inverter_max_output_kw is not None:
        sources[CONF_INVERTER_MAX_OUTPUT_ENTITY] = inverter.entities["inverter_max_output"]
    return sources


def limit_sources_for(cfg: Mapping[str, Any], states: Mapping[str, Any]) -> dict[str, str]:
    """The limit sensors of an existing entry's inverter that read a number now.

    The entry keeps the prefix GivTCP gave its entities, so it is read from the wiring.
    """
    prefix = device_prefix(cfg)
    found = limit_sensors(prefix, dict(states)) if prefix else {}
    conf = {
        "battery_capacity_kwh": CONF_BATTERY_CAPACITY_ENTITY,
        "inverter_max_output": CONF_INVERTER_MAX_OUTPUT_ENTITY,
    }
    return {conf[key]: entity_id for key, entity_id in found.items()}


def serial_in_entity_id(entity_id: str) -> str | None:
    """The inverter serial an entity id carries, None when it is not a GivTCP entity id."""
    match = _ENTITY_SERIAL.match(entity_id or "")
    return match["serial"] if match else None


def serials_in_wiring(values: Mapping[str, Any]) -> set[str]:
    """The serials the chosen required entities carry. Entities with no serial add none."""
    found = {serial_in_entity_id(str(values.get(key) or "")) for key in WIRING_REQUIRED}
    found.discard(None)
    return found  # type: ignore[return-value]


def serials_match(entity_serials: set[str], unique_id: str | None) -> bool:
    """True when every serial in the entities is the one the entry was created for.

    No serial in the entities (hand-picked sensors with another naming) or a manual entry
    cannot be compared, so both pass. Serials differ in case between GivTCP's serial sensor and
    its entity ids, so the comparison ignores it.
    """
    if unique_id in (None, MANUAL_SERIAL):
        return True
    return all(serial.lower() == str(unique_id).lower() for serial in entity_serials)


def with_serial(wiring: dict[str, str], serial: str) -> dict[str, str]:
    """*wiring* with the serial added under the key the entry stores it under."""
    return {**wiring, CONF_INVERTER_SERIAL: serial}
