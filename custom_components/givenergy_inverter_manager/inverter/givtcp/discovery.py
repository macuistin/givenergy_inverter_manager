"""
inverter/givtcp/discovery.py: GivTCP inverter auto-discovery for GivEnergy Inverter Manager.

Supports both GivTCP v2 (battery_soc suffix) and v3 (soc suffix).
Also auto-reads battery capacity from the inverter's capacity sensor.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ...const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)
from ...core.system_types import (
    EMS_SUFFIXES,
    GATEWAY_SUFFIXES,
    InverterFacts,
    SystemKind,
    classify,
)

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
    kind: SystemKind = SystemKind.UNKNOWN
    invertor_type: str | None = None  # GivTCP's own word for the model, as published
    givtcp_version: str | None = None
    modules: int | None = None  # battery modules found, None when it cannot be told
    parallel_units: int | None = None  # All-In-Ones a Gateway says are in parallel
    evidence: tuple[str, ...] = ()
    confidence: str = "low"
    suffixes: frozenset[str] = frozenset()  # every suffix the device publishes

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

    def facts(self) -> InverterFacts:
        """The device as the selection rules and the identity see it."""
        return InverterFacts(
            serial=self.serial,
            prefix=self.prefix,
            kind=self.kind,
            complete=self.is_fully_configured,
            can_schedule=self.has_charge_scheduling,
            version=self.givtcp_version,
            modules=self.modules,
            parallel_units=self.parallel_units,
            roles=tuple(sorted(self.entities.values())),
        )


_NOT_A_SERIAL = frozenset({"", "0", "unknown", "unavailable", "none"})
_DEVICE_DOMAINS = ("sensor", "number", "switch", "select", "button", "time")
# A device with no serial sensor is still an inverter-like device when it reports a GivTCP
# version and one of these: an All-In-One, a Gateway or an EMS may not publish the serial sensor.
_INVERTER_MARKERS = ("_soc", "_battery_soc", *GATEWAY_SUFFIXES, *EMS_SUFFIXES)
BATTERY_SERIAL_SUFFIX = "_battery_serial_number"
VERSION_SUFFIX = "_givtcp_version"
REAL_TIME_CONTROL_SUFFIX = "_real_time_control"
TYPE_SUFFIX = "_invertor_type"


def _usable(state: Any) -> str | None:
    """The state text, or None when it is missing, unavailable or empty."""
    text = str(getattr(state, "state", "") or "").strip()
    return None if text.lower() in ("unavailable", "unknown", "") else text


def _candidate_prefixes(all_states: dict) -> list[str]:
    """Device prefixes that look like an inverter-like device, longest first.

    A device is named by what it publishes, never by a fixed prefix: GivTCP lets the user change
    it for each inverter (HADEVICEPREFIX). The serial sensor names a device, and so does the
    version sensor on a device that also publishes a state of charge or a Gateway or EMS value.
    """
    found: dict[str, str] = {}
    for entity_id in all_states:
        if not entity_id.startswith("sensor."):
            continue
        name = entity_id[len("sensor.") :]
        if name.endswith(SERIAL_SENSOR_SUFFIX):
            found[name[: -len(SERIAL_SENSOR_SUFFIX)]] = entity_id
    for entity_id in all_states:
        if entity_id.startswith("sensor.") and entity_id.endswith(VERSION_SUFFIX):
            prefix = entity_id[len("sensor.") : -len(VERSION_SUFFIX)]
            if prefix not in found and any(
                f"sensor.{prefix}{marker}" in all_states for marker in _INVERTER_MARKERS
            ):
                found[prefix] = ""
    return sorted(found, key=len, reverse=True)


def _tail(prefix: str) -> str:
    """The last word of a device prefix in capitals, which GivTCP makes from the serial."""
    return prefix.rsplit("_", 1)[-1].upper()


def _suffixes_of(prefix: str, others: list[str], all_states: dict) -> dict[str, str]:
    """{suffix: entity_id} for the entities that belong to *prefix* and to no longer prefix."""
    longer = [other for other in others if other != prefix and other.startswith(prefix + "_")]
    owned: dict[str, str] = {}
    for entity_id in all_states:
        domain, _, name = entity_id.partition(".")
        if domain not in _DEVICE_DOMAINS or not name.startswith(prefix + "_"):
            continue
        if any(name.startswith(other + "_") for other in longer):
            continue
        owned.setdefault(name[len(prefix) :], entity_id)
    return owned


def _count_battery_modules(all_states: dict) -> int:
    """Battery modules that report a real serial. A module that answers with zeros is a ghost."""
    count = 0
    for entity_id, state in all_states.items():
        if entity_id.startswith("sensor.") and entity_id.endswith(BATTERY_SERIAL_SUFFIX):
            text = _usable(state)
            if text is not None and text.lower() not in _NOT_A_SERIAL and set(text) != {"0"}:
                count += 1
    return count


def _read_int(all_states: dict, entity_id: str) -> int | None:
    text = _usable(all_states.get(entity_id))
    try:
        return int(float(text)) if text is not None else None
    except ValueError:
        return None


def discover_givtcp_inverters(all_states: dict) -> list[GivTCPInverter]:
    """
    Scan HA entity states for GivTCP inverter-like devices: hybrids, AC-coupled inverters,
    All-In-Ones, three-phase inverters, Gateways and EMS plants.

    Accepts a dict of {entity_id: state_object} — HA-free and testable. Returns the devices
    sorted by serial number. Devices are found by the entities they publish, not by a fixed
    `givtcp_` prefix, so a prefix the user changed in GivTCP is found too. Handles both GivTCP v2
    (_battery_soc suffix) and v3 (_soc suffix).
    """
    prefixes = _candidate_prefixes(all_states)
    inverters = [_build_inverter(prefix, prefixes, all_states) for prefix in prefixes]
    if len(inverters) == 1:
        inverters[0].modules = _count_battery_modules(all_states) or None
    inverters.sort(key=lambda i: i.serial)
    return inverters


def _build_inverter(prefix: str, prefixes: list[str], all_states: dict) -> GivTCPInverter:
    owned = _suffixes_of(prefix, prefixes, all_states)
    serial_state = all_states.get(f"sensor.{prefix}{SERIAL_SENSOR_SUFFIX}")
    # A device with no serial sensor (a Gateway or an EMS may have none) is named by its prefix.
    serial = _usable(serial_state) or (prefix if serial_state is not None else _tail(prefix))
    inverter = GivTCPInverter(serial=serial, prefix=prefix, display_name=f"GivTCP {serial}")
    inverter.suffixes = frozenset(owned)

    # ── Battery SoC: try GivTCP v3 name first, fall back to v2 ───────────────
    for soc_suffix in ("_soc", "_battery_soc"):
        candidate = f"sensor.{prefix}{soc_suffix}"
        if candidate in all_states:
            inverter.entities["battery_soc"] = candidate
            break
    else:
        inverter.missing_entities.append(f"sensor.{prefix}_soc")

    # ── All other entities ───────────────────────────────────────────────────
    for key, suffix in ENTITY_SUFFIXES.items():
        candidate = f"{ENTITY_DOMAINS.get(key, 'sensor')}.{prefix}{suffix}"
        if candidate in all_states:
            inverter.entities[key] = candidate
        else:
            inverter.missing_entities.append(candidate)

    # ── Battery capacity value from the sensor state ─────────────────────────
    cap_state = all_states.get(inverter.entities.get("battery_capacity_kwh", ""))
    if cap_state is not None and (text := _usable(cap_state)) is not None:
        with contextlib.suppress(ValueError, TypeError):
            inverter.battery_capacity_kwh = float(text)

    # ── What kind of device it is ────────────────────────────────────────────
    inverter.invertor_type = _usable(all_states.get(f"sensor.{prefix}{TYPE_SUFFIX}"))
    inverter.givtcp_version = _usable(all_states.get(f"sensor.{prefix}{VERSION_SUFFIX}"))
    inverter.parallel_units = _read_int(all_states, f"sensor.{prefix}_parallel_total_aio_number")
    verdict = classify(inverter.suffixes, inverter.invertor_type)
    inverter.kind, inverter.evidence, inverter.confidence = (
        verdict.kind,
        verdict.evidence,
        verdict.confidence,
    )
    return inverter


# The wiring entities whose names end in a known GivTCP suffix, best first. The device prefix is
# what is left once the domain and the suffix are taken off.
_PREFIX_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CONF_BATTERY_POWER, ("_battery_power",)),
    (CONF_SOLAR_POWER, ("_pv_power",)),
    (CONF_GRID_POWER, ("_grid_power",)),
    (CONF_HOUSE_LOAD, ("_load_power",)),
    (CONF_BATTERY_SOC, ("_soc", "_battery_soc")),
    (CONF_TARGET_SOC_ENTITY, ("_target_soc",)),
)


def device_prefix(cfg: Any) -> str:
    """The prefix GivTCP gave this inverter's entities, for the entities derived from it.

    GivTCP lets the user change the prefix for each inverter, so it is read from the entities the
    wiring already names, which discovery or the user chose. A prefix is trusted when it carries
    the inverter's serial or when two of those entities agree on it, so hand-picked sensors with
    other names do not produce one. Otherwise it is the default prefix and the serial.
    """
    serial = str(cfg.get(CONF_INVERTER_SERIAL) or "")
    derived = [p for p in (_prefix_from(cfg, key, sfx) for key, sfx in _PREFIX_PROBES) if p]
    for prefix in derived:
        if (serial and serial.lower() in prefix.lower()) or derived.count(prefix) >= 2:  # noqa: PLR2004
            return prefix
    return f"{GIVTCP_PREFIX}{serial}" if serial else ""


def _prefix_from(cfg: Any, key: str, suffixes: tuple[str, ...]) -> str:
    name = str(cfg.get(key) or "").partition(".")[2]
    for suffix in suffixes:
        if len(name) > len(suffix) and name.endswith(suffix):
            return name[: -len(suffix)]
    return ""


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


# GivTCP keeps its own day, night and export rates as sensors named by the inverter serial. The
# setup tariff page offers them as starting values and nothing else reads them.
GIVTCP_RATE_SUFFIXES: dict[str, str] = {
    "day": "_day_rate",
    "night": "_night_rate",
    "export": "_export_rate",
}

# GivTCP's battery pause: a mode select, and a start and an end time. GivTCP 3.6 publishes a time
# as a drop-down (select), a time picker (time) or both, by one of its settings, so the select is
# looked for first and the time entity next.
BATTERY_PAUSE_MODE_SUFFIX = "_battery_pause_mode"
BATTERY_PAUSE_START_SUFFIX = "_battery_pause_start_time_slot"
BATTERY_PAUSE_END_SUFFIX = "_battery_pause_end_time_slot"
PAUSE_TIME_DOMAINS = ("select", "time")


@dataclass(frozen=True)
class BatteryPauseEntities:
    """The entity ids GivTCP publishes the battery pause under, for one device prefix."""

    mode: str
    start: tuple[str, ...]  # best first
    end: tuple[str, ...]


def battery_pause_entities(prefix: str) -> BatteryPauseEntities:
    """The mode entity and the start and end entities of the pause, for a device prefix.

    The device may not publish them, and may start to later, so they are never stored in the
    config. The reader looks for them on every read.
    """
    return BatteryPauseEntities(
        mode=f"select.{prefix}{BATTERY_PAUSE_MODE_SUFFIX}",
        start=tuple(f"{d}.{prefix}{BATTERY_PAUSE_START_SUFFIX}" for d in PAUSE_TIME_DOMAINS),
        end=tuple(f"{d}.{prefix}{BATTERY_PAUSE_END_SUFFIX}" for d in PAUSE_TIME_DOMAINS),
    )


# GivTCP names the temperature sensor "invertor". The other spelling is tried second, in case
# a GivTCP release or a renamed entity uses it.
INVERTER_TEMPERATURE_SPELLINGS = ("invertor", "inverter")


def inverter_temperature_entity_ids(serial: str) -> list[str]:
    """The entity ids GivTCP could publish the inverter temperature under, best first."""
    return temperature_entity_ids_for(f"{GIVTCP_PREFIX}{serial.lower()}")


def temperature_entity_ids_for(prefix: str) -> list[str]:
    """The same, for a device prefix, which GivTCP lets the user change."""
    return [
        f"sensor.{prefix}_{spelling}_temperature" for spelling in INVERTER_TEMPERATURE_SPELLINGS
    ]


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


def clock_time(state: Any) -> str | None:
    """The state as HH:MM, or None for a missing, unavailable or non-time state."""
    match = _CLOCK_TIME.match(str(state.state).strip()) if state is not None else None
    return f"{int(match['hour']):02d}:{match['minute']}" if match else None


def _active_slot(
    number: int, start_id: str, end_id: str, get_state: Callable[[str], Any]
) -> ActiveChargeSlot | None:
    start, end = clock_time(get_state(start_id)), clock_time(get_state(end_id))
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
