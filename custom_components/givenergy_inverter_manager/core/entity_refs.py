"""
entity_refs.py: keep finding a GivTCP entity after Home Assistant's entity id for it changes.

The integration stores each GivTCP entity as an entity id. GivTCP 3.6 and 3.6.1 reset entity ids
to their defaults when a discovery config changed, and a GivTCP upgrade can rename or remove
entities, so a stored id can stop matching while the entity registry still knows the same entity
by its unique id. This module learns the unique id of each configured entity while the stored id
still matches, and uses it to find the entity again under its new id.

  1. The configured id exists: use it, and remember its unique id.
  2. It does not, and the remembered unique id now belongs to another id: use that one.
  3. Neither works: the entity is missing, and the caller raises one repair that names it.

Nothing here reads Home Assistant. The caller gives it the three questions it needs answered.
Pure Python.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)

# The twelve wiring keys that hold a GivTCP entity id. wizard/wiring.py names the same set.
REFERENCE_KEYS: tuple[str, ...] = (
    CONF_SOLAR_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_POWER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_TARGET_SOC_ENTITY,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
)


@dataclass(frozen=True)
class Registry:
    """The three questions about Home Assistant's entities, as functions."""

    exists: Callable[[str], bool]  # is there a state or a registry entry for this id
    identity_of: Callable[[str], tuple[str, str] | None]  # (platform, unique id) of an id
    entity_id_for: Callable[[str, str, str], str | None]  # (domain, platform, unique id) -> id


@dataclass
class Resolution:
    """What resolving the wiring found."""

    cfg: dict[str, Any]
    learned: dict[str, dict[str, str]] = field(default_factory=dict)
    renamed: dict[str, tuple[str, str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def resolve(
    cfg: Mapping[str, Any],
    remembered: Mapping[str, Mapping[str, str]],
    registry: Registry,
    keys: Collection[str] = REFERENCE_KEYS,
) -> Resolution:
    """The config with every renamed entity pointed at its current id, and what was learned."""
    result = Resolution(dict(cfg))
    for key in keys:
        entity_id = str(cfg.get(key) or "")
        if not entity_id:
            continue
        if registry.exists(entity_id):
            learned = _learned(entity_id, remembered.get(key), registry)
            if learned is not None:
                result.learned[key] = learned
            continue
        current = _renamed_to(entity_id, remembered.get(key), registry)
        if current is not None:
            result.cfg[key] = current
            result.renamed[key] = (entity_id, current)
        else:
            result.missing.append(key)
    return result


def _learned(
    entity_id: str, known: Mapping[str, str] | None, registry: Registry
) -> dict[str, str] | None:
    """The reference to remember for an id that matches, None when it is already remembered."""
    if known is not None and known.get("entity_id") == entity_id:
        return None
    identity = registry.identity_of(entity_id)
    if identity is None:
        return None
    return {"entity_id": entity_id, "platform": identity[0], "unique_id": identity[1]}


def _renamed_to(
    old_id: str, known: Mapping[str, str] | None, registry: Registry
) -> str | None:
    if not known or not known.get("unique_id") or not known.get("platform"):
        return None
    domain = old_id.partition(".")[0]
    current = registry.entity_id_for(domain, known["platform"], known["unique_id"])
    return current if current and current != old_id and registry.exists(current) else None


def clean_remembered(stored: object) -> dict[str, dict[str, str]]:
    """The remembered references from storage, anything that is not one dropped."""
    if not isinstance(stored, dict):
        return {}
    good: dict[str, dict[str, str]] = {}
    for key, ref in stored.items():
        if isinstance(ref, dict) and all(isinstance(ref.get(f), str) and ref[f] for f in _FIELDS):
            good[str(key)] = {f: ref[f] for f in _FIELDS}
    return good


_FIELDS = ("entity_id", "platform", "unique_id")
