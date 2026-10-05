"""button.py — Button platform for GivEnergy Inverter Manager."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .entity import GivEnergyEntity
from .logging import get_logger

_LOG = get_logger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([GivEnergyRefreshDashboardButton(coordinator)])


class GivEnergyRefreshDashboardButton(GivEnergyEntity, ButtonEntity):
    """Button that regenerates the dashboard YAML file."""

    _attr_translation_key = "refresh_dashboard"
    _attr_icon = "mdi:view-dashboard-edit"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh_dashboard"

    @property
    def available(self) -> bool:
        """The button regenerates a file, so it works whether or not GivTCP is publishing."""
        return True

    async def async_press(self) -> None:
        await self.coordinator.hass.services.async_call(
            DOMAIN,
            "get_dashboard_yaml",
            blocking=True,
        )
