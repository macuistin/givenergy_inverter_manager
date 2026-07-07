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

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_TARGET_TEMP,
    DEFAULT_IMMERSION_HYSTERESIS,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_TARGET_TEMP,
    DOMAIN,
    INTEGRATION_VERSION,
)
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
    async_add_entities(
        [
            GivEnergyChargeTargetOverride(coordinator),
            ImmersionTargetTempNumber(coordinator),
            ImmersionMinTempNumber(coordinator),
            ImmersionHysteresisNumber(coordinator),
        ]
    )


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


def _make_device_info(coordinator: GivEnergyCoordinator) -> dict:
    return {
        "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
        "name": "GivEnergy Inverter Manager",
        "manufacturer": "GivEnergy",
        "model": "Inverter Manager",
        "sw_version": INTEGRATION_VERSION,
    }


class _ImmersionNumberBase(CoordinatorEntity[GivEnergyCoordinator], RestoreNumber, NumberEntity):
    """Base for immersion temperature number controls."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        coordinator: GivEnergyCoordinator,
        key: str,
        default: float,
        config_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = _make_device_info(coordinator)
        self._config_key = config_key
        self._value: float = default

    @property
    def native_value(self) -> float:
        return self._value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_number = await self.async_get_last_number_data()
        if last_number and last_number.native_value is not None:
            await self._apply(last_number.native_value)

    async def _apply(self, value: float) -> None:
        """Store value and push to coordinator. Override in subclass."""
        raise NotImplementedError

    def _persist(self, value: float) -> None:
        """Write to entry.data so coordinator.__init__ reads the correct value on restart."""
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry,
            data={**self.coordinator.entry.data, self._config_key: value},
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._apply(value)
        self._persist(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ImmersionTargetTempNumber(_ImmersionNumberBase):
    """Upper temperature — immersion turns off when water reaches this."""

    _attr_name = "Immersion Target Temperature"
    _attr_native_min_value = 40.0
    _attr_native_max_value = 75.0
    _attr_native_step = 1.0

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(
            coordinator,
            "immersion_target_temp",
            DEFAULT_IMMERSION_TARGET_TEMP,
            CONF_IMMERSION_TARGET_TEMP,
        )

    async def _apply(self, value: float) -> None:
        # Guard: target must be at least 1°C above min to prevent short-cycling
        value = max(value, self.coordinator.immersion_min_temp + 1)
        self._value = value
        self.coordinator.immersion_target_temp = value
        _LOG.info("Immersion target temperature set to %.0f°C", value)


class ImmersionMinTempNumber(_ImmersionNumberBase):
    """Lower temperature — immersion forced on below this (legionella / restart threshold)."""

    _attr_name = "Immersion Minimum Temperature"
    _attr_native_min_value = 30.0
    _attr_native_max_value = 60.0
    _attr_native_step = 1.0

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(
            coordinator, "immersion_min_temp", DEFAULT_IMMERSION_MIN_TEMP, CONF_IMMERSION_MIN_TEMP
        )

    async def _apply(self, value: float) -> None:
        # Guard: min must be at least 1°C below target to prevent short-cycling
        value = min(value, self.coordinator.immersion_target_temp - 1)
        self._value = value
        self.coordinator.immersion_min_temp = value
        _LOG.info("Immersion minimum temperature set to %.0f°C", value)


class ImmersionHysteresisNumber(_ImmersionNumberBase):
    """Hysteresis — only restart after cooling this many degrees below target."""

    _attr_name = "Immersion Restart Hysteresis"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 15.0
    _attr_native_step = 1.0

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(
            coordinator,
            "immersion_hysteresis",
            DEFAULT_IMMERSION_HYSTERESIS,
            CONF_IMMERSION_HYSTERESIS,
        )

    async def _apply(self, value: float) -> None:
        self._value = value
        self.coordinator.immersion_hysteresis_c = value
        _LOG.info("Immersion restart hysteresis set to %.0f°C", value)
