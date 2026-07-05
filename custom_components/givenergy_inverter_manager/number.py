"""
number.py — Number platform for GivEnergy Inverter Manager.

Provides one number entity:

  Overnight Charge Target Override (GivEnergyChargeTargetOverride)
    A 10-100% slider representing the manual override SoC target.
    Only active when the companion "Enable charge target override" switch
    (in switch.py) is turned on. When that switch is off the integration
    uses its automatic forecast-based calculation.

    Deliberately has no 0 or "auto" sentinel — 0% is not a meaningful
    charge target and using it as a mode flag is confusing. The switch
    carries the mode; the number carries only the value.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyCoordinator
from .logging import get_logger

_LOG = get_logger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager number entities."""
    coordinator: GivEnergyCoordinator = entry.runtime_data
    async_add_entities([GivEnergyChargeTargetOverride(coordinator)])


class GivEnergyChargeTargetOverride(CoordinatorEntity[GivEnergyCoordinator], NumberEntity):
    """
    Manual override for tonight's charge target SoC.

    Pair with the "Enable charge target override" switch in switch.py.
    This entity holds the value; the switch determines whether it is used.
    Range 10-100% — no zero sentinel, no hidden mode logic.
    """

    _attr_has_entity_name = True
    _attr_name = "Overnight Charge Target Override"
    _attr_native_min_value = 10
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-charging-80"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_charge_target_override"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }
        self._value: float = 80  # sensible default; only applied when the switch is on

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        """Store the override target. The coordinator reads this when override is enabled."""
        self._value = value
        self.coordinator.override_charge_target = int(value)
        _LOG.info("Charge target override value set to %d%%", int(value))
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
