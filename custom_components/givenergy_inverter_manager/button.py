"""button.py — Button platform for GivEnergy Inverter Manager."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyCoordinator
from .logging import get_logger

_LOG = get_logger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GivEnergyCoordinator = entry.runtime_data
    async_add_entities([GivEnergyRefreshDashboardButton(coordinator)])


class GivEnergyRefreshDashboardButton(ButtonEntity):
    """Button that regenerates the dashboard YAML file."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_dashboard"
    _attr_icon = "mdi:view-dashboard-edit"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh_dashboard"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }

    async def async_press(self) -> None:
        await self._coordinator.hass.services.async_call(
            DOMAIN,
            "get_dashboard_yaml",
            blocking=True,
        )
