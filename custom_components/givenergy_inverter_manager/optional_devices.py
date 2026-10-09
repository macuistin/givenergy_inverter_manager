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

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_helpers import effective_config
from .const import DOMAIN
from .core.devices import Device, installed_devices
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
    "switch", "auto_immersion", Device.IMMERSION_SWITCH, "Auto Immersion Divert"
)
IMMERSION_MANAGED = DeviceEntity(
    "switch", "immersion_managed", Device.IMMERSION_SWITCH, "Immersion Heater (Managed)"
)
IMMERSION_SCHEDULE = DeviceEntity(
    "switch",
    "immersion_schedule",
    Device.IMMERSION_THERMOSTAT,
    "Immersion Scheduled Heating",
)
IMMERSION_TARGET = DeviceEntity(
    "number", "immersion_target_temp", Device.IMMERSION_THERMOSTAT, "Immersion Target Temperature"
)
IMMERSION_MINIMUM = DeviceEntity(
    "number", "immersion_min_temp", Device.IMMERSION_THERMOSTAT, "Immersion Minimum Temperature"
)
IMMERSION_RESTART_GAP = DeviceEntity(
    "number", "immersion_hysteresis", Device.IMMERSION_THERMOSTAT, "Immersion Restart Gap"
)
DEVICE_ENTITIES: tuple[DeviceEntity, ...] = (
    AUTO_IMMERSION,
    IMMERSION_MANAGED,
    IMMERSION_SCHEDULE,
    IMMERSION_TARGET,
    IMMERSION_MINIMUM,
    IMMERSION_RESTART_GAP,
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


@callback
def remove_orphaned_entities(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Delete the registry entries of entities whose device is no longer present."""
    present = present_devices(entry)
    if Device.EV_CHARGER not in present and _charger_may_exist(hass):
        present = present | {Device.EV_CHARGER}
    registry = er.async_get(hass)
    for platform, key, device in _device_entities():
        if device in present:
            continue
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id is not None:
            registry.async_remove(entity_id)
            _LOG.info("Removed %s, its %s is no longer present", entity_id, device.value)
