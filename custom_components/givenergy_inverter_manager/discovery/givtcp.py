"""

givtcp.py — GivTCP inverter auto-discovery for GivEnergy Inverter Manager.

Supports both GivTCP v2 (battery_soc suffix) and v3 (soc suffix).
Also auto-reads battery capacity from the inverter's capacity sensor.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

SERIAL_SENSOR_SUFFIX = "_invertor_serial_number"
GIVTCP_PREFIX = "givtcp_"
BATTERY_CYCLES_SUFFIX = "_battery_cycles"

# GivTCP exposes ten charge slots per inverter, named ..._charge_start_time_slot_N.
MAX_CHARGE_SLOTS = 10
UNUSED_SLOT_TIME = "00:00:00"

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


def discover_givtcp_inverters(all_states: dict) -> list[GivTCPInverter]:  # noqa: C901, PLR0912
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


def discover_battery_cycle_entities(all_states: dict) -> list[str]:
    """
    Find the BMS lifetime cycle counters GivTCP publishes for each battery pack.

    Each pack is named sensor.givtcp_<battery serial>_battery_cycles, with the
    battery serial rather than the inverter serial. Accepts a dict of
    {entity_id: state_object} and returns the entity IDs sorted.
    """
    start = f"sensor.{GIVTCP_PREFIX}"
    return sorted(
        entity_id
        for entity_id in all_states
        if entity_id.startswith(start) and entity_id.endswith(BATTERY_CYCLES_SUFFIX)
    )


def get_suggested_entities(inverter: GivTCPInverter) -> dict[str, str]:
    """Return config key → entity_id dict for all discovered entities."""
    return dict(inverter.entities)


# ── Rates GivTCP holds ───────────────────────────────────────────────────────

# GivTCP keeps its own day, night and export rates as sensors named by the inverter serial.
GIVTCP_RATE_SUFFIXES: dict[str, str] = {
    "day": "_day_rate",
    "night": "_night_rate",
    "export": "_export_rate",
}


def givtcp_rate_entity_ids(serial: str) -> dict[str, str]:
    """The entity ids of GivTCP's day, night and export rate sensors for this inverter."""
    return {
        name: f"sensor.{GIVTCP_PREFIX}{serial}{suffix}"
        for name, suffix in GIVTCP_RATE_SUFFIXES.items()
    }


# ── Charge slots the integration does not manage ─────────────────────────────

_TRAILING_NUMBER = re.compile(r"^(?P<stem>.*?)(?P<number>\d+)$")
_CLOCK_TIME = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?$")


@dataclass(frozen=True)
class ActiveChargeSlot:
    """A charge slot whose start differs from its end, so the inverter will charge in it."""

    number: int
    start_entity_id: str
    end_entity_id: str
    start: str  # HH:MM
    end: str  # HH:MM

    @property
    def label(self) -> str:
        return f"Slot {self.number} ({self.start} to {self.end})"


def describe_charge_slots(slots: Sequence[ActiveChargeSlot]) -> str:
    """The slots as one readable line, for example 'Slot 2 (00:00 to 08:00)'."""
    return ", ".join(slot.label for slot in slots)


def _split_trailing_number(entity_id: str) -> tuple[str, int] | None:
    match = _TRAILING_NUMBER.match(entity_id)
    return (match["stem"], int(match["number"])) if match else None


def _clock_time(state: Any) -> str | None:
    """The state as HH:MM, or None for a missing, unavailable or non-time state."""
    match = _CLOCK_TIME.match(str(state.state).strip()) if state is not None else None
    return f"{int(match['hour']):02d}:{match['minute']}" if match else None


def _active_slot(
    number: int, start_id: str, end_id: str, get_state: Callable[[str], Any]
) -> ActiveChargeSlot | None:
    start, end = _clock_time(get_state(start_id)), _clock_time(get_state(end_id))
    if start is None or end is None or start == end:
        return None
    return ActiveChargeSlot(number, start_id, end_id, start, end)


def find_other_active_charge_slots(
    start_entity_id: str, end_entity_id: str, get_state: Callable[[str], Any]
) -> list[ActiveChargeSlot]:
    """
    Find charge slots, other than the configured one, that have a charge window set.

    The configured start and end entities end in the slot number (slot 1 for
    GivTCP). The sibling slots share that prefix with another number. A slot is
    active when its start differs from its end, and 00:00 to 00:00 means unused.
    A sibling that does not exist or is unavailable is ignored.
    `get_state` returns the state object for an entity id, or None.
    """
    start = _split_trailing_number(start_entity_id)
    end = _split_trailing_number(end_entity_id)
    if start is None or end is None or start[1] != end[1]:
        return []
    slots = (
        _active_slot(number, f"{start[0]}{number}", f"{end[0]}{number}", get_state)
        for number in range(1, MAX_CHARGE_SLOTS + 1)
        if number != start[1]
    )
    return [slot for slot in slots if slot is not None]
