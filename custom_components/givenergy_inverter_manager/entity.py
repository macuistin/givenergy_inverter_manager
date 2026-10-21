"""
entity.py — shared base class for every GivEnergy Inverter Manager entity.

Holds the one copy of the device registry entry, so all platforms attach their
entities to the same device. Unique ids and entity ids stay with each platform.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyCoordinator
from .core.devices import DeviceGroup, group_name

_DEVICE_MODEL = "Inverter Manager"


def device_info(coordinator: GivEnergyCoordinator, group: DeviceGroup) -> DeviceInfo:
    """The registry entry for a group. The EV charger and immersion hang off the main device."""
    entry_id = coordinator.entry.entry_id
    if group is DeviceGroup.MAIN:
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=group_name(group),
            manufacturer=DEVICE_MANUFACTURER,
            model=_DEVICE_MODEL,
            sw_version=INTEGRATION_VERSION,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{group.value}")},
        name=group_name(group),
        manufacturer=DEVICE_MANUFACTURER,
        model=group_name(group),
        via_device=(DOMAIN, entry_id),
    )


class GivEnergyEntity(CoordinatorEntity[GivEnergyCoordinator]):
    """Base for all entities. Sets the entity naming mode and the shared device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GivEnergyCoordinator, group: DeviceGroup = DeviceGroup.MAIN
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info(coordinator, group)
