"""
switch.py — Switch platform for GivEnergy Inverter Manager.

Provides five switches, three of them only with an immersion switch:

  Auto Immersion Divert (GivEnergyAutoImmersionSwitch)
    Created only while an immersion switch is configured. Master on/off for the
    automatic immersion divert logic. When off, the coordinator's override_immersion
    is set to False and the immersion will not be turned on automatically regardless
    of solar surplus.

  Immersion Heater Managed (GivEnergyImmersionControlSwitch)
    Created only while an immersion switch is configured. It shows the
    coordinator's divert decision. The coordinator's ImmersionActuator applies
    that decision to the real switch on every update, whether or not this
    entity is enabled. Turning this switch on runs the heater until the water
    reaches its target. Turning it off holds the heater off for the cooldown.

  Immersion Scheduled Heating (GivEnergyImmersionScheduleSwitch)
    Created only while both an immersion switch and a water temperature sensor are
    configured. Off by default and restored after a restart. While on, the coordinator heats
    the water to its target in the cheapest rate window and in time for the ready times.
    Solar surplus diversion by day is unchanged.

  Force Skip Overnight Charge (GivEnergySkipChargeOverrideSwitch)
    When on, overrides the overnight charge decision to skip charging
    regardless of what the forecast says. Useful for manually preventing
    a charge on a night when the battery is already adequate.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.devices import Device
from .entity import GivEnergyEntity
from .logging import get_logger
from .optional_devices import (
    AUTO_IMMERSION,
    IMMERSION_MANAGED,
    IMMERSION_SCHEDULE,
    async_add_entities_per_device,
    present_devices,
)

_LOG = get_logger(__name__)


# Coordinator-driven — no parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager switches."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            GivEnergySkipChargeOverrideSwitch(coordinator),
            GivEnergyChargeTargetOverrideSwitch(coordinator),
        ]
    )

    def _switches_of(device: Device) -> list[SwitchEntity]:
        if device is Device.IMMERSION_SWITCH:
            return [
                GivEnergyAutoImmersionSwitch(coordinator),
                GivEnergyImmersionControlSwitch(coordinator),
            ]
        if device is Device.IMMERSION_THERMOSTAT:
            return [GivEnergyImmersionScheduleSwitch(coordinator)]
        return []

    if Device.IMMERSION_SWITCH not in present_devices(entry):
        _remove_managed_switch(hass, entry)

    async_add_entities_per_device(entry, async_add_entities, _switches_of)


def _managed_switch_unique_id(entry: GivEnergyConfigEntry) -> str:
    return f"{entry.entry_id}_immersion_managed"


def _remove_managed_switch(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Delete the managed switch left behind after the immersion switch was cleared."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, _managed_switch_unique_id(entry)
    )
    if entity_id is not None:
        registry.async_remove(entity_id)
        _LOG.info("Removed the managed immersion switch %s, no immersion switch is set", entity_id)


class GivEnergyAutoImmersionSwitch(
    GivEnergyEntity, RestoreEntity, SwitchEntity
):
    """Switch to enable/disable automatic immersion divert logic."""

    _attr_name = AUTO_IMMERSION.name

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._auto_immersion_enabled: bool = True  # instance variable — not shared across entities
        self._attr_unique_id = f"{coordinator.entry.entry_id}_auto_immersion"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._auto_immersion_enabled = last.state == STATE_ON
            if not self._auto_immersion_enabled:
                self.coordinator.override_immersion = False

    @property
    def is_on(self) -> bool:
        return self._auto_immersion_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._auto_immersion_enabled = True
        self.coordinator.override_immersion = None  # Let auto logic run
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._auto_immersion_enabled = False
        self.coordinator.override_immersion = False
        self.async_write_ha_state()


class GivEnergyImmersionControlSwitch(GivEnergyEntity, SwitchEntity):
    """View and command on the coordinator's immersion actuator.

    The actuator drives the real switch every cycle. This entity shows its decision and
    lets the user override it.
    """

    _attr_name = IMMERSION_MANAGED.name

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = _managed_switch_unique_id(coordinator.entry)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.should_divert_immersion

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Manual override: force immersion on and run until target temperature is reached."""
        await self.coordinator.immersion.manual_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off now; auto-divert resumes after cooldown expires."""
        await self.coordinator.immersion.manual_off()
        await self.coordinator.async_request_refresh()


class GivEnergyImmersionScheduleSwitch(GivEnergyEntity, RestoreEntity, SwitchEntity):
    """Opt in to scheduled heating: the cheapest rate window and the ready-by times.

    Off until the user turns it on. The state survives a restart. The coordinator reads
    the flag every cycle, so turning it on or off takes effect at the next update.
    """

    _attr_name = IMMERSION_SCHEDULE.name
    _attr_icon = "mdi:water-boiler-auto"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_immersion_schedule"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.immersion_schedule_enabled = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.coordinator.immersion_schedule_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.immersion_schedule_enabled = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.immersion_schedule_enabled = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class GivEnergySkipChargeOverrideSwitch(GivEnergyEntity, SwitchEntity):
    """Switch to force skip overnight charging regardless of decision logic.

    Stores the override on the coordinator so it is honoured by every future
    engine run, not just the current in-memory snapshot.
    """

    _attr_name = "Force Skip Overnight Charge"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_skip_charge_override"

    @property
    def is_on(self) -> bool:
        return self.coordinator.override_skip_charge

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.override_skip_charge = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.override_skip_charge = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class GivEnergyChargeTargetOverrideSwitch(
    GivEnergyEntity, RestoreEntity, SwitchEntity
):
    """
    Switch to enable or disable the manual charge target override.

    Off (default): the integration calculates the charge target automatically
      from the solar forecast, tariff, and battery state.
    On: tonight's charge target is taken from the companion Number entity
      ("Overnight Charge Target Override") instead.

    Separating mode from value means the number slider always shows a
    meaningful SoC percentage, never a confusing "0 = auto" sentinel.
    """

    _attr_name = "Enable Charge Target Override"
    _attr_icon = "mdi:battery-charging-outline"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_charge_target_override_enabled"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            self.coordinator.override_charge_enabled = True
            await self.coordinator.async_request_refresh()

    @property
    def is_on(self) -> bool:
        return self.coordinator.override_charge_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Activate the override. The coordinator applies the number's current value."""
        self.coordinator.override_charge_enabled = True
        _LOG.info("Charge target override enabled")
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Deactivate override — coordinator returns to automatic calculation."""
        self.coordinator.override_charge_enabled = False
        _LOG.info("Charge target override disabled — returning to auto mode")
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
