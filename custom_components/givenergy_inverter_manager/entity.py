"""
entity.py — shared base class for every GivEnergy Inverter Manager entity.

Holds the one copy of the device registry entry, so all platforms attach their
entities to the same device. Unique ids and entity ids stay with each platform.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.devices import DeviceGroup, group_name

_DEVICE_MODEL = "Inverter Manager"


def _main_device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=group_name(DeviceGroup.MAIN),
        manufacturer=DEVICE_MANUFACTURER,
        model=_DEVICE_MODEL,
        sw_version=INTEGRATION_VERSION,
    )


def async_register_main_device(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Create the main device before the platforms, so the other devices can point at its id."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **_main_device_info(entry.entry_id)
    )


def _parent_link(hass: HomeAssistant, entry_id: str) -> dict[str, object]:
    """The link from a group device to the main device, in the form this Home Assistant takes.

    Newer releases take the id of the parent device. Older ones take its identifiers.
    """
    if "via_device_id" in getattr(DeviceInfo, "__annotations__", {}):
        main = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry_id)})
        return {"via_device_id": main.id} if main is not None else {}
    return {"via_device": (DOMAIN, entry_id)}


def device_info(coordinator: GivEnergyCoordinator, group: DeviceGroup) -> DeviceInfo:
    """The registry entry for a group. The EV charger and immersion hang off the main device."""
    entry_id = coordinator.entry.entry_id
    if group is DeviceGroup.MAIN:
        return _main_device_info(entry_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{group.value}")},
        name=group_name(group),
        manufacturer=DEVICE_MANUFACTURER,
        model=group_name(group),
        **_parent_link(coordinator.hass, entry_id),
    )


class GivEnergyEntity(CoordinatorEntity[GivEnergyCoordinator]):
    """Base for all entities. Sets the entity naming mode and the shared device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GivEnergyCoordinator, group: DeviceGroup = DeviceGroup.MAIN
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info(coordinator, group)
