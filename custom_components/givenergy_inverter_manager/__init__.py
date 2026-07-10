"""
__init__.py — GivEnergy Inverter Manager Home Assistant integration entry point.

Sets up the integration from a config entry:
  1. Creates the GivEnergyCoordinator and triggers its first data fetch.
  2. Forwards setup to all platforms (sensor, switch, number).
  3. Registers an options listener so tariff/threshold changes take effect
     immediately without requiring a full HA restart.

Also handles:
  async_unload_entry  — clean teardown when the integration is removed.
  async_reload_entry  — called by the options listener on config change.
  async_migrate_entry — version migration hook for future schema changes.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import GivEnergyCoordinator
from .dashboard import async_register_services, async_unregister_services
from .logging import get_logger, log_startup

_LOG = get_logger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GivEnergy Inverter Manager from a config entry."""
    _LOG.debug("Setting up entry %s (%s)", entry.entry_id, entry.title)

    coordinator = GivEnergyCoordinator(hass, entry)

    # Restore persisted energy accumulators so today/week/month survive HA restarts.
    await coordinator._acc.async_load()
    coordinator._acc.restore_battery_stats(coordinator._battery_stats)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(
            translation_domain="givenergy_inverter_manager",
            translation_key="config_entry_not_ready",
            translation_placeholders={"error": str(err)},
        ) from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register services (idempotent — safe to call on every entry setup)
    await async_register_services(hass)

    # Emit startup entity config to the verbose logger (opt-in, debug only)
    cfg = dict(entry.data)
    cfg.update(entry.options)
    log_startup(_LOG, cfg)

    _LOG.info("Set up %s successfully", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOG.debug("Unloading entry %s (%s)", entry.entry_id, entry.title)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        async_unregister_services(hass)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry — called when the user saves new options."""
    _LOG.debug("Reloading entry %s after options change", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to new version."""
    _LOG.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        # Future migrations go here
        pass

    return True
