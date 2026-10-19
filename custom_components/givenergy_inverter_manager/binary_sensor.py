"""
binary_sensor.py: Binary sensor platform for GivEnergy Inverter Manager.

Two on/off sensors for automations that follow the tariff:

  Cheapest Rate Active
    On while the cheapest timed rate period is in force. It is the on/off form of the
    Is On Cheapest Rate sensor.

  Cheap Rate Active
    On while any period cheaper than the base rate is in force, so the whole run of cheap hours
    counts, not only the cheapest part of it.

Both are off on a tariff with no timed rate period. Names and icons are translated: the
entity's translation key is its unique id suffix, and strings.json and icons.json hold the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import sensor_values as values
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.engine import CoordinatorData
from .entity import GivEnergyEntity

# Coordinator-driven, so no parallel updates are needed
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GivEnergyBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a GivEnergy Manager binary sensor."""

    value_fn: Callable[[CoordinatorData], bool]


BINARY_SENSOR_DESCRIPTIONS: tuple[GivEnergyBinarySensorDescription, ...] = (
    GivEnergyBinarySensorDescription(
        key="cheapest_rate_active",
        translation_key="cheapest_rate_active",
        icon="mdi:cash-check",
        value_fn=values.cheapest_rate_active,
    ),
    GivEnergyBinarySensorDescription(
        key="cheap_rate_active",
        translation_key="cheap_rate_active",
        icon="mdi:cash-clock",
        value_fn=values.cheap_rate_active,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        GivEnergyBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class GivEnergyBinarySensor(GivEnergyEntity, BinarySensorEntity):
    """A binary sensor read from the coordinator's data."""

    entity_description: GivEnergyBinarySensorDescription

    def __init__(
        self,
        coordinator: GivEnergyCoordinator,
        description: GivEnergyBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """True while the tariff condition holds, None before the first update."""
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)
