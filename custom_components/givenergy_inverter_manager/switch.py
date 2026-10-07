"""
switch.py — Switch platform for GivEnergy Inverter Manager.

Provides three switches:

  Auto Immersion Divert (GivEnergyAutoImmersionSwitch)
    Master on/off for the automatic immersion divert logic. When off, the
    coordinator's override_immersion is set to False and the immersion will
    not be turned on automatically regardless of solar surplus.

  Immersion Heater Managed (GivEnergyImmersionControlSwitch)
    Only created if an immersion switch entity is configured. It shows the
    coordinator's divert decision. The coordinator's ImmersionActuator applies
    that decision to the real switch on every update, whether or not this
    entity is enabled. Turning this switch on runs the heater until the water
    reaches its target. Turning it off holds the heater off for the cooldown.

  Force Skip Overnight Charge (GivEnergySkipChargeOverrideSwitch)
    When on, overrides the overnight charge decision to skip charging
    regardless of what the forecast says. Useful for manually preventing
    a charge on a night when the battery is already adequate.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .config_helpers import effective_config
from .const import CONF_IMMERSION_SWITCH
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .entity import GivEnergyEntity
from .logging import get_logger

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

    entities = [
        GivEnergyAutoImmersionSwitch(coordinator),
        GivEnergySkipChargeOverrideSwitch(coordinator),
        GivEnergyChargeTargetOverrideSwitch(coordinator),
    ]

    # Only add immersion control switch if an immersion entity is configured
    if effective_config(entry).get(CONF_IMMERSION_SWITCH):
        entities.append(GivEnergyImmersionControlSwitch(coordinator))

    async_add_entities(entities)


class GivEnergyAutoImmersionSwitch(
    GivEnergyEntity, RestoreEntity, SwitchEntity
):
    """Switch to enable/disable automatic immersion divert logic."""

    _attr_name = "Auto Immersion Divert"

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

    _attr_name = "Immersion Heater (Managed)"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_immersion_managed"

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
