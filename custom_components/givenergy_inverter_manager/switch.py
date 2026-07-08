"""
switch.py — Switch platform for GivEnergy Inverter Manager.

Provides three switches:

  Auto Immersion Divert (GivEnergyAutoImmersionSwitch)
    Master on/off for the automatic immersion divert logic. When off, the
    coordinator's override_immersion is set to False and the immersion will
    not be turned on automatically regardless of solar surplus.

  Immersion Heater Managed (GivEnergyImmersionControlSwitch)
    Only created if an immersion switch entity is configured. This switch
    applies the coordinator's divert decision to the real switch entity
    on each coordinator update. Turning it on/off manually sets an override
    that persists until cleared via the Auto Immersion Divert switch.

  Force Skip Overnight Charge (GivEnergySkipChargeOverrideSwitch)
    When on, overrides the overnight charge decision to skip charging
    regardless of what the forecast says. Useful for manually preventing
    a charge on a night when the battery is already adequate.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_IMMERSION_SWITCH, DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyCoordinator
from .logging import get_logger

_LOG = get_logger(__name__)


# Coordinator-driven — no parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager switches."""
    coordinator: GivEnergyCoordinator = entry.runtime_data

    entities = [
        GivEnergyAutoImmersionSwitch(coordinator),
        GivEnergySkipChargeOverrideSwitch(coordinator),
        GivEnergyChargeTargetOverrideSwitch(coordinator),
    ]

    # Only add immersion control switch if an immersion entity is configured
    if entry.data.get(CONF_IMMERSION_SWITCH):
        entities.append(GivEnergyImmersionControlSwitch(coordinator))

    async_add_entities(entities)


class GivEnergyAutoImmersionSwitch(
    CoordinatorEntity[GivEnergyCoordinator], RestoreEntity, SwitchEntity
):
    """Switch to enable/disable automatic immersion divert logic."""

    _attr_has_entity_name = True
    _attr_name = "Auto Immersion Divert"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._auto_immersion_enabled: bool = True  # instance variable — not shared across entities
        self._attr_unique_id = f"{coordinator.entry.entry_id}_auto_immersion"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }

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


class GivEnergyImmersionControlSwitch(CoordinatorEntity[GivEnergyCoordinator], SwitchEntity):
    """Switch that applies the coordinator's immersion divert decision to the actual switch."""

    _attr_has_entity_name = True
    _attr_name = "Immersion Heater (Managed)"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_immersion_managed"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.should_divert_immersion

    def _is_dry_run(self) -> bool:
        return self.coordinator.is_dry_run

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Manual override: force immersion on."""
        self.coordinator.override_immersion = True
        immersion_switch = self.coordinator.entry.data.get(CONF_IMMERSION_SWITCH)
        if immersion_switch and not self._is_dry_run():
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": immersion_switch}, blocking=True
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Manual override: force immersion off."""
        self.coordinator.override_immersion = False
        immersion_switch = self.coordinator.entry.data.get(CONF_IMMERSION_SWITCH)
        if immersion_switch and not self._is_dry_run():
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": immersion_switch}, blocking=True
            )
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Apply immersion decision to the real switch when coordinator updates."""
        if self.coordinator.data is None:
            self.async_write_ha_state()
            return
        immersion_switch = self.coordinator.entry.data.get(CONF_IMMERSION_SWITCH)
        if not immersion_switch:
            self.async_write_ha_state()
            return

        should_be_on = self.coordinator.data.should_divert_immersion
        # Use coordinator proxy so this path is testable without a real hass
        current_state = self.coordinator._get_state(immersion_switch)
        current_on = current_state is not None and current_state.state == "on"

        if should_be_on != current_on:
            service = "turn_on" if should_be_on else "turn_off"
            if self.coordinator.is_dry_run:
                action = (
                    f"Would {service} immersion heater "
                    f"(reason: {self.coordinator.data.divert_reason})"
                )
                _LOG.info("DRY RUN: %s", action)
                self.coordinator.data.dry_run_last_skipped = action
            else:
                _LOG.debug(
                    "Immersion: %s (reason: %s)",
                    service,
                    self.coordinator.data.divert_reason,
                )
                self.hass.async_create_task(
                    self.coordinator._call_service(
                        "switch", service, {"entity_id": immersion_switch}, blocking=False
                    )
                )

        self.async_write_ha_state()


class GivEnergySkipChargeOverrideSwitch(CoordinatorEntity[GivEnergyCoordinator], SwitchEntity):
    """Switch to force skip overnight charging regardless of decision logic.

    Stores the override on the coordinator so it is honoured by every future
    engine run, not just the current in-memory snapshot.
    """

    _attr_has_entity_name = True
    _attr_name = "Force Skip Overnight Charge"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_skip_charge_override"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }

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
    CoordinatorEntity[GivEnergyCoordinator], RestoreEntity, SwitchEntity
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

    _attr_has_entity_name = True
    _attr_name = "Enable Charge Target Override"
    _attr_icon = "mdi:battery-charging-outline"

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_charge_target_override_enabled"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }
        self._enabled: bool = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._enabled = last.state == STATE_ON
            if not self._enabled:
                self.coordinator.override_charge_target = None

    @property
    def is_on(self) -> bool:
        return self._enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Activate override — coordinator will now use override_charge_target."""
        self._enabled = True
        _LOG.info("Charge target override enabled")
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Deactivate override — coordinator returns to automatic calculation."""
        self._enabled = False
        self.coordinator.override_charge_target = None
        _LOG.info("Charge target override disabled — returning to auto mode")
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
