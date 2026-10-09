"""
devices.py - which optional devices the dashboard shows, and how it hides them.

The EV charger, the immersion switch and the immersion temperature sensor are optional, and
a stored dashboard (the YAML file, or a paste into the raw editor) outlives a change to any of
them. So every card that needs a device carries a Lovelace visibility condition on one entity
of that device, its sentinel. The condition hides the card while the sentinel is unavailable
or missing and shows it when the device arrives, with no regeneration.

A device that is not installed yet has no registry entry. The cards that wait for it point at
the entity ID Home Assistant will give it, worked out from the entity's name.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path
from typing import Any

from ..const import NAME
from ..core.devices import Device
from ..optional_devices import DEVICE_ENTITIES
from ..sensor_descriptions import SENSOR_DESCRIPTIONS
from .registry import Registry

# One entity per device that exists exactly while the device does.
SENTINELS: dict[Device, str] = {
    Device.EV_CHARGER: "ev_charger_state",
    Device.IMMERSION_SWITCH: "immersion_managed",
    Device.IMMERSION_SENSOR: "immersion_water_temperature",
    Device.IMMERSION_THERMOSTAT: "immersion_target_temp",
}

_STRINGS = Path(__file__).resolve().parent.parent / "strings.json"
_UNAVAILABLE = "unavailable"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _read_sensor_names() -> dict[str, str]:
    """The sensors' names by translation key, as Home Assistant builds entity IDs from them."""
    sensors = json.loads(_STRINGS.read_text(encoding="utf-8"))["entity"]["sensor"]
    return {key: value["name"] for key, value in sensors.items()}


# Read once when the module is imported, which Home Assistant does off the event loop.
_SENSOR_NAMES = _read_sensor_names()


@cache
def _entity_names() -> dict[str, tuple[str, str]]:
    """Unique ID suffix -> (domain, name) for every entity that needs a device."""
    names = {
        d.key: ("sensor", _SENSOR_NAMES[d.translation_key or d.key])
        for d in SENSOR_DESCRIPTIONS
        if d.requires is not None
    }
    names.update({e.key: (e.platform, e.name) for e in DEVICE_ENTITIES})
    return names


def expected_entity_id(suffix: str) -> str | None:
    """The entity ID Home Assistant gives a new entity of ours with this unique ID suffix."""
    found = _entity_names().get(suffix)
    if found is None:
        return None
    domain, name = found
    return f"{domain}.{_slug(NAME)}_{_slug(name)}"


def _state_condition(entity: str, **test: str) -> dict[str, Any]:
    return {"condition": "state", "entity": entity, **test}


def with_visibility(card: dict | None, conditions: list[dict]) -> dict | None:
    """The card shown only while every condition holds, and any it already has. None stays None."""
    if card is None:
        return None
    return {**card, "visibility": [*card.get("visibility", []), *conditions]}


def _powerset(devices: tuple[Device, ...]) -> Iterable[tuple[Device, ...]]:
    sizes = range(len(devices) + 1)
    return itertools.chain.from_iterable(itertools.combinations(devices, n) for n in sizes)


class Devices:
    """Which optional devices exist now, and the conditions that show a card for them."""

    def __init__(self, registry: Registry) -> None:
        self._reg = registry
        self.present = frozenset(
            device for device, sentinel in SENTINELS.items() if registry.get(sentinel)
        )

    def entity(self, device: Device, suffix: str) -> str | None:
        """The entity with this unique ID suffix. Expected, not looked up, for an absent device."""
        if device in self.present:
            return self._reg.get(suffix)
        return expected_entity_id(suffix)

    def sentinel(self, device: Device) -> str:
        """The entity whose state says whether the device is there."""
        found = self.entity(device, SENTINELS[device])
        if found is None:
            raise LookupError(f"no entity ID for the {device.value} sentinel")
        return found

    def visible_with(self, *devices: Device) -> list[dict]:
        """Conditions that hold while every one of these devices is present."""
        return [
            _state_condition(self.sentinel(device), state_not=_UNAVAILABLE) for device in devices
        ]

    def visible_without(self, *devices: Device) -> list[dict]:
        """Conditions that hold while none of these devices is present."""
        return [_state_condition(self.sentinel(device), state=_UNAVAILABLE) for device in devices]

    def visible_while_on(self, entity: str) -> list[dict]:
        """A condition that holds while this switch is on."""
        return [_state_condition(entity, state="on")]

    def visible_with_any(self, *devices: Device) -> list[dict]:
        """One condition that holds while at least one of these devices is present."""
        present = [
            _state_condition(self.sentinel(device), state_not=_UNAVAILABLE) for device in devices
        ]
        return [{"condition": "or", "conditions": present}]

    def show_with(self, card: dict | None, *devices: Device) -> dict | None:
        """The card, shown while every one of these devices is present."""
        return with_visibility(card, self.visible_with(*devices))

    def variants(
        self,
        devices: tuple[Device, ...],
        build: Callable[[frozenset[Device]], dict | None],
    ) -> list[dict]:
        """One card for each combination of these devices being present or not.

        A card that lists entities cannot hide one row, so each combination gets the card
        built for exactly the devices present, and the condition shows the matching one.
        """
        cards = []
        for subset in _powerset(devices):
            absent = tuple(device for device in devices if device not in subset)
            conditions = self.visible_with(*subset) + self.visible_without(*absent)
            card = with_visibility(build(frozenset(subset)), conditions)
            if card is not None:
                cards.append(card)
        return cards
