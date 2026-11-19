"""
time.py — Time platform for GivEnergy Inverter Manager.

Provides the two EV charge window controls (controls.py): the time the car's grid charge starts
and the time it ends, each day. They exist while an EV charger is set, like the other EV
entities, and each writes its saved option.

Names and icons are translated: the entity's translation key is its unique id suffix, and
strings.json and icons.json hold the rest. optional_devices.DeviceEntity.name repeats the
English name for the dashboard, and tests/test_translations.py keeps the two equal.
"""

from __future__ import annotations

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controls import control_times
from .coordinator import GivEnergyConfigEntry
from .core.devices import Device
from .optional_devices import async_add_entities_per_device

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager time entities."""
    coordinator = entry.runtime_data

    def _times_of(device: Device) -> list[TimeEntity]:
        return [*control_times(coordinator, device)]

    async_add_entities_per_device(entry, async_add_entities, _times_of)
