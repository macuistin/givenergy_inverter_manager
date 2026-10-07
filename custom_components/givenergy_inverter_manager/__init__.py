"""
__init__.py — GivEnergy Inverter Manager Home Assistant integration entry point.

Sets up the integration from a config entry:
  1. Creates the GivEnergyCoordinator and triggers its first data fetch.
  2. Forwards setup to all platforms (sensor, switch, number).
  3. Registers an options listener so tariff/threshold changes take effect
     immediately without requiring a full HA restart.

Also handles:
  async_unload_entry  — clean teardown when the integration is removed.
  async_reload_entry  — called by the update listener when a reload-relevant setting changes.
  async_migrate_entry — version migration hook for future schema changes.
"""

from __future__ import annotations

import copy
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_TARGET_TEMP,
    DOMAIN,
)
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .logging import get_logger, log_startup
from .optional_devices import remove_orphaned_entities
from .services import (
    DASHBOARD_FILENAME,
    async_register_services,
    async_unregister_services,
    loaded_entries,
)
from .strategy import async_register_strategy

_LOG = get_logger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON]

# Sensors removed from the integration. Their registry entries stay behind as
# "no longer provided" until something deletes them, so setup does.
_RETIRED_SENSOR_KEYS: tuple[str, ...] = (
    "pre_boost_export_recommended",
    "pre_boost_export_kwh",
    "pre_boost_export_net_gain",
)

_LIVE_SETTINGS: dict[str, str] = {
    CONF_IMMERSION_TARGET_TEMP: "immersion_target_temp",
    CONF_IMMERSION_MIN_TEMP: "immersion_min_temp",
    CONF_IMMERSION_HYSTERESIS: "immersion_hysteresis_c",
}


def _reload_relevant(entry: GivEnergyConfigEntry) -> tuple[dict, dict]:
    """Return the entry contents that need a reload when they change."""
    data = {k: v for k, v in entry.data.items() if k not in _LIVE_SETTINGS}
    return copy.deepcopy(data), copy.deepcopy(dict(entry.options))


def _apply_live_settings(coordinator: GivEnergyCoordinator, entry: GivEnergyConfigEntry) -> None:
    """Copy the immersion temperature settings onto the running coordinator."""
    for conf_key, attr in _LIVE_SETTINGS.items():
        if entry.data.get(conf_key) is not None:
            setattr(coordinator, attr, float(entry.data[conf_key]))


def _make_update_listener(entry: GivEnergyConfigEntry):
    """Build the update listener for *entry*.

    A change that only touches the immersion temperature settings (moved with the
    number entities) updates the running coordinator. Any other change reloads.
    """
    reload_state = _reload_relevant(entry)

    async def _on_entry_updated(hass: HomeAssistant, updated: GivEnergyConfigEntry) -> None:
        nonlocal reload_state
        current = _reload_relevant(updated)
        if current == reload_state:
            _apply_live_settings(updated.runtime_data, updated)
            return
        reload_state = current
        await async_reload_entry(hass, updated)

    return _on_entry_updated


def _remove_retired_sensors(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Delete the registry entries of retired sensors that belong to this config entry."""
    registry = er.async_get(hass)
    for key in _RETIRED_SENSOR_KEYS:
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{entry.entry_id}_{key}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
            _LOG.info("Removed the retired sensor %s", entity_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service actions once, independent of any config entry."""
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> bool:
    """Set up GivEnergy Inverter Manager from a config entry."""
    _LOG.debug("Setting up entry %s (%s)", entry.entry_id, entry.title)

    coordinator = GivEnergyCoordinator(hass, entry)

    # Restore persisted energy accumulators so today/week/month survive HA restarts.
    await coordinator.async_restore_state()

    # Home Assistant raises ConfigEntryNotReady, with the translated UpdateFailed
    # message, when the first refresh fails.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    _remove_retired_sensors(hass, entry)
    remove_orphaned_entities(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_make_update_listener(entry)))

    # async_setup runs once per start; this restores services removed by the last unload.
    await async_register_services(hass)

    try:
        await async_register_strategy(hass)
    except Exception:
        _LOG.exception("Could not register the dashboard strategy")

    # Create a placeholder dashboard file so YAML-mode lovelace can reference it
    # immediately without requiring the user to run Refresh Dashboard first.
    dashboard_path = os.path.join(hass.config.config_dir, DASHBOARD_FILENAME)

    def _write_placeholder() -> bool:
        if os.path.exists(dashboard_path):
            return False
        with open(dashboard_path, "w", encoding="utf-8") as fh:
            fh.write("views: []\n")
        return True

    if await hass.async_add_executor_job(_write_placeholder):
        _LOG.info("Created dashboard placeholder at %s", dashboard_path)

    # Emit startup entity config to the verbose logger (opt-in, debug only)
    cfg = dict(entry.data)
    cfg.update(entry.options)
    log_startup(_LOG, cfg)

    _LOG.info("Set up %s successfully", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> bool:
    """Unload a config entry."""
    _LOG.debug("Unloading entry %s (%s)", entry.entry_id, entry.title)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if not [e for e in loaded_entries(hass) if e.entry_id != entry.entry_id]:
            async_unregister_services(hass)
    return bool(unload_ok)


async def async_reload_entry(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Reload config entry — called when the user saves new options."""
    _LOG.debug("Reloading entry %s after options change", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to new version."""
    _LOG.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        return True

    _LOG.error("Cannot migrate config entry from unknown version %s", config_entry.version)
    return False
