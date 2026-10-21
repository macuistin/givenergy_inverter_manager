"""
entity.py — shared base class for every GivEnergy Inverter Manager entity.

Holds the one copy of the device registry entry, so all platforms attach their
entities to the same device. Unique ids and entity ids stay with each platform.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DOMAIN, INTEGRATION_VERSION, NAME
from .coordinator import GivEnergyCoordinator

_DEVICE_MODEL = "Inverter Manager"


class GivEnergyEntity(CoordinatorEntity[GivEnergyCoordinator]):
    """Base for all entities. Sets the entity naming mode and the shared device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=_DEVICE_MODEL,
            sw_version=INTEGRATION_VERSION,
        )
