"""
optional_devices.py - creates and removes the entities that belong to an optional device.

The EV charger, the immersion switch and the immersion temperature sensor are all optional,
and an install can gain or lose one at any time. An entity that needs a device is created
only while the device is present:

  * at setup, for the devices present then
  * when a device appears while the entry is loaded (an EV charger discovered later)
  * after a reload, which an options change to the immersion entities triggers

The registry entries of a device that is gone are removed at setup, so nothing is left
behind as "no longer provided".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_helpers import effective_config
from .const import CONF_SURPLUS_DIVERT_MIN_W, CONF_SURPLUS_DIVERT_SOC, DOMAIN
from .core.devices import Device, DeviceGroup, group_present, installed_devices
from .discovery import discover_ev_chargers
from .logging import get_logger
from .sensor_descriptions import SENSOR_DESCRIPTIONS

if TYPE_CHECKING:
    from homeassistant.helpers.entity import Entity

    from .coordinator import GivEnergyConfigEntry

_LOG = get_logger(__name__)


@dataclass(frozen=True)
class DeviceEntity:
    """A switch or number that needs an optional device.

    name is the entity's own name. The dashboard predicts the entity ID of a device that
    is not installed yet from it, so the platform class and the dashboard share this one copy.
    """

    platform: str
    key: str
    requires: Device
    name: str


AUTO_IMMERSION = DeviceEntity(
    "switch", "auto_immersion", Device.IMMERSION_SWITCH, "Auto Divert"
)
IMMERSION_MANAGED = DeviceEntity(
    "switch", "immersion_managed", Device.IMMERSION_SWITCH, "Heater (Managed)"
)
IMMERSION_SCHEDULE = DeviceEntity(
    "switch",
    "immersion_schedule",
    Device.IMMERSION_THERMOSTAT,
    "Scheduled Heating",
)
IMMERSION_TARGET = DeviceEntity(
    "number", "immersion_target_temp", Device.IMMERSION_THERMOSTAT, "Target Temperature"
)
IMMERSION_MINIMUM = DeviceEntity(
    "number", "immersion_min_temp", Device.IMMERSION_THERMOSTAT, "Minimum Temperature"
)
IMMERSION_RESTART_GAP = DeviceEntity(
    "number", "immersion_hysteresis", Device.IMMERSION_THERMOSTAT, "Restart Gap"
)
DIVERT_MIN_SOC = DeviceEntity(
    "number", CONF_SURPLUS_DIVERT_SOC, Device.IMMERSION_SWITCH, "Divert minimum SoC"
)
DIVERT_MIN_SURPLUS = DeviceEntity(
    "number",
    CONF_SURPLUS_DIVERT_MIN_W,
    Device.IMMERSION_SWITCH,
    "Divert minimum surplus",
)
DEVICE_ENTITIES: tuple[DeviceEntity, ...] = (
    AUTO_IMMERSION,
    IMMERSION_MANAGED,
    IMMERSION_SCHEDULE,
    IMMERSION_TARGET,
    IMMERSION_MINIMUM,
    IMMERSION_RESTART_GAP,
    DIVERT_MIN_SOC,
    DIVERT_MIN_SURPLUS,
)


def present_devices(entry: GivEnergyConfigEntry) -> frozenset[Device]:
    """The optional devices this entry has now: merged config, and the charger discovery found."""
    charger_found = getattr(entry.runtime_data, "ev_charger_brand", None) is not None
    return installed_devices(effective_config(entry), ev_charger_found=charger_found)


@callback
def async_add_entities_per_device(
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[Device], list[Entity]],
) -> None:
    """Add the entities of each device present now, and of each device that appears later.

    build returns the entities of one device. It is called once per device while the entry
    stays loaded. A reload starts again, so a device the options just added is picked up.
    """
    added: set[Device] = set()

    @callback
    def _add_new_devices() -> None:
        new = present_devices(entry) - added
        added.update(new)
        entities = [entity for device in sorted(new) for entity in build(device)]
        if entities:
            async_add_entities(entities)

    _add_new_devices()
    entry.async_on_unload(entry.runtime_data.async_add_listener(_add_new_devices))


def _device_entities() -> Iterator[tuple[str, str, Device]]:
    """Every entity that needs a device: its platform, its unique ID suffix and the device."""
    for description in SENSOR_DESCRIPTIONS:
        if description.requires is not None:
            yield "sensor", description.key, description.requires
    for entity in DEVICE_ENTITIES:
        yield entity.platform, entity.key, entity.requires


def _charger_may_exist(hass: HomeAssistant) -> bool:
    """True when an EV charger is there to discover, or its integration may still be loading.

    The coordinator discovers a charger on its second update, after setup. So at setup a
    charger can be present and not yet counted. A scan of the states answers for it. While
    Home Assistant is still starting, the charger's own integration may not have created its
    entities yet, so the entities of ours are kept rather than deleted and made again, which
    would lose the user's customisations. The next reload removes them if no charger shows.
    """
    if not hass.is_running:
        return True
    return bool(discover_ev_chargers({s.entity_id: s for s in hass.states.async_all()}))


def _present_or_expected(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> frozenset[Device]:
    """The devices present, and the EV charger too while one may still be discovered."""
    present = present_devices(entry)
    if Device.EV_CHARGER not in present and _charger_may_exist(hass):
        return present | {Device.EV_CHARGER}
    return present


def _group_of_device(entry: GivEnergyConfigEntry, device: dr.DeviceEntry) -> DeviceGroup | None:
    """The group a registry device stands for, or None when it is not one of this entry's."""
    for group in DeviceGroup:
        suffix = "" if group is DeviceGroup.MAIN else f"_{group.value}"
        if (DOMAIN, f"{entry.entry_id}{suffix}") in device.identifiers:
            return group
    return None


@callback
def can_remove_device(entry: GivEnergyConfigEntry, device: dr.DeviceEntry) -> bool:
    """True when the user may delete this device: its hardware is gone, or it is not ours.

    The main device and a device whose hardware is still set stay. Deleting one would only
    make the next update create it again.
    """
    group = _group_of_device(entry, device)
    if group is None:
        return True
    return not group_present(group, present_devices(entry))


@callback
def remove_stale_devices(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Remove the devices of hardware that is no longer set, once their entities are gone."""
    present = _present_or_expected(hass, entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        group = _group_of_device(entry, device)
        if group is None or group_present(group, present):
            continue
        registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
        _LOG.info("Removed the %s device, its hardware is no longer present", group.value)


@callback
def async_inherit_main_area(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Put a device created later in the area of the main device.

    Only a new device is placed, so an area the user later changes or clears is left alone.
    """

    @callback
    def _created(event: Event) -> None:
        if event.data["action"] != "create":
            return
        registry = dr.async_get(hass)
        device = registry.async_get(event.data["device_id"])
        if device is None or entry.entry_id not in device.config_entries:
            return
        if _group_of_device(entry, device) in (None, DeviceGroup.MAIN) or device.area_id:
            return
        main = next(
            (
                d
                for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
                if _group_of_device(entry, d) is DeviceGroup.MAIN
            ),
            None,
        )
        if main is not None and main.area_id:
            registry.async_update_device(device.id, area_id=main.area_id)

    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _created))


@callback
def remove_orphaned_entities(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Delete the registry entries of entities whose device is no longer present."""
    present = _present_or_expected(hass, entry)
    registry = er.async_get(hass)
    for platform, key, device in _device_entities():
        if device in present:
            continue
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id is not None:
            registry.async_remove(entity_id)
            _LOG.info("Removed %s, its %s is no longer present", entity_id, device.value)
