"""
number.py — Number platform for GivEnergy Inverter Manager.

Provides one number entity, plus three immersion temperature controls:

  Overnight Charge Target Override (GivEnergyChargeTargetOverride)
    A 10-100% slider representing the manual override SoC target.
    Only active when the companion "Enable charge target override" switch
    (in switch.py) is turned on. When that switch is off the integration
    uses its automatic forecast-based calculation.

    Deliberately has no 0 or "auto" sentinel — 0% is not a meaningful
    charge target and using it as a mode flag is confusing. The switch
    carries the mode; the number carries only the value.

  Immersion target, minimum and restart gap (ImmersionTargetTempNumber and its siblings)
    Created only while the immersion switch and its temperature sensor are both set, as
    the thermostat acts on no less.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_TARGET_TEMP,
    DEFAULT_IMMERSION_HYSTERESIS,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_TARGET_TEMP,
)
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.devices import Device
from .entity import GivEnergyEntity
from .logging import get_logger
from .optional_devices import (
    IMMERSION_MINIMUM,
    IMMERSION_RESTART_GAP,
    IMMERSION_TARGET,
    async_add_entities_per_device,
)

_LOG = get_logger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager number entities."""
    coordinator = entry.runtime_data
    async_add_entities([GivEnergyChargeTargetOverride(coordinator)])

    def _numbers_of(device: Device) -> list[NumberEntity]:
        if device is not Device.IMMERSION_THERMOSTAT:
            return []
        return [
            ImmersionTargetTempNumber(coordinator),
            ImmersionMinTempNumber(coordinator),
            ImmersionHysteresisNumber(coordinator),
        ]

    async_add_entities_per_device(entry, async_add_entities, _numbers_of)


class GivEnergyChargeTargetOverride(
    GivEnergyEntity, RestoreNumber, NumberEntity
):
    """
    Manual override for tonight's charge target SoC.

    Pair with the "Enable charge target override" switch in switch.py.
    This entity sets coordinator.override_charge_value; the switch sets
    coordinator.override_charge_enabled. The coordinator derives the effective
    target from both, so moving the slider never enables the override.
    Range 10-100% — no zero sentinel, no hidden mode logic.
    """

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

    @property
    def native_value(self) -> float:
        return self.coordinator.override_charge_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_number = await self.async_get_last_number_data()
        if last_number and last_number.native_value is not None:
            restored = int(last_number.native_value)
            self.coordinator.override_charge_value = int(
                min(self._attr_native_max_value, max(self._attr_native_min_value, restored))
            )
            if self.coordinator.override_charge_enabled:
                await self.coordinator.async_request_refresh()

    async def async_set_native_value(self, value: float) -> None:
        """Store the override value. It only takes effect while the switch is on."""
        self.coordinator.override_charge_value = int(value)
        _LOG.info("Charge target override value set to %d%%", int(value))
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class _ImmersionNumberBase(GivEnergyEntity, RestoreNumber, NumberEntity):
    """Base for immersion temperature number controls."""

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
        self._persist(self._value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ImmersionTargetTempNumber(_ImmersionNumberBase):
    """Upper temperature — immersion turns off when water reaches this."""

    _attr_name = IMMERSION_TARGET.name
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

    _attr_name = IMMERSION_MINIMUM.name
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
    """Restart gap — how many degrees below target before restarting is allowed."""

    _attr_name = IMMERSION_RESTART_GAP.name
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
        _LOG.info("Immersion restart gap set to %.0f°C", value)
