"""
__init__.py — GivEnergy Inverter Manager Home Assistant integration entry point.

Sets up the integration from a config entry:
  1. Creates the GivEnergyCoordinator and triggers its first data fetch.
  2. Forwards setup to all platforms (sensor, switch, number).
  3. Registers an options listener so tariff/threshold changes take effect
     immediately without requiring a full HA restart.

Also handles:
  async_unload_entry  — clean teardown when the integration is removed.
  async_reload_entry  — called by the update listener when a change needs a reload.
  async_migrate_entry — version migration hook for future schema changes.
"""

from __future__ import annotations

import copy

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .config_helpers import effective_config
from .const import DOMAIN
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.alt_heat_conversion import converted_alt_heat
from .core.default_enabled import keys_to_enable
from .core.devices import alt_heat_warnings
from .core.reload_policy import Effect, change_effect, changed_keys
from .dashboard_notice import async_announce_dashboard, async_dismiss_announcement
from .logging import get_logger, log_startup
from .optional_devices import remove_orphaned_entities
from .services import async_register_services, async_unregister_services, loaded_entries
from .stored_dashboard_repair import async_watch_stored_dashboard
from .strategy import async_register_strategy

_LOG = get_logger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]

# Sensors removed from the integration. Their registry entries stay behind as
# "no longer provided" until something deletes them, so setup does.
_RETIRED_SENSOR_KEYS: tuple[str, ...] = (
    "pre_boost_export_recommended",
    "pre_boost_export_kwh",
    "pre_boost_export_net_gain",
)

# Buttons removed from the integration. Refresh Dashboard rewrote the YAML file that the
# dashboard strategy replaced.
_RETIRED_BUTTON_KEYS: tuple[str, ...] = ("refresh_dashboard",)

def _make_update_listener(entry: GivEnergyConfigEntry):
    """Build the update listener for *entry*.

    The listener keeps the merged config of the last save it saw. A change that needs a
    reload (core/reload_policy.py) reloads the entry. Any other change is applied to the
    running coordinator, and nothing reloads.
    """
    previous = copy.deepcopy(effective_config(entry))

    async def _on_entry_updated(hass: HomeAssistant, updated: GivEnergyConfigEntry) -> None:
        nonlocal previous
        current = copy.deepcopy(effective_config(updated))
        effect = change_effect(previous, current)
        changed = changed_keys(previous, current)
        previous = current
        if effect is Effect.RELOAD:
            await async_reload_entry(hass, updated)
        elif effect is Effect.LIVE:
            await updated.runtime_data.async_apply_config_change(changed)

    return _on_entry_updated


# Repair issues the integration no longer raises. A live install may still hold one, so
# setup deletes it. Deleting an issue that is not there does nothing.
_RETIRED_ISSUE_IDS: tuple[str, ...] = ("givtcp_rates_differ",)


def _convert_oil_price(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Turn the oil price options of 0.17 into alternative heating, once.

    Runs before the coordinator is built, so everything after it reads the new keys. The
    update listener is not registered yet, so the write does not reload the entry. A second
    setup finds the saved alt_heat_enabled and does nothing.
    """
    converted = converted_alt_heat(entry.data, entry.options)
    if converted is None:
        return
    data, options = converted
    hass.config_entries.async_update_entry(entry, data=data, options=options)
    _LOG.info("Converted the oil price settings to alternative heating with the label Oil")


def _warn_about_alt_heat(entry: GivEnergyConfigEntry) -> None:
    """Say once at setup what alternative heating still needs, when it is on and incomplete."""
    for warning in alt_heat_warnings(effective_config(entry)):
        _LOG.warning("Alternative water heating is on, but there is %s", warning)


def _remove_retired_entities(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Delete the registry entries of retired sensors and buttons of this config entry."""
    registry = er.async_get(hass)
    retired = ((Platform.SENSOR, _RETIRED_SENSOR_KEYS), (Platform.BUTTON, _RETIRED_BUTTON_KEYS))
    for platform, keys in retired:
        for key in keys:
            entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
            if entity_id is not None:
                registry.async_remove(entity_id)
                _LOG.info("Removed the retired %s %s", platform.value, entity_id)


def _remove_retired_issues(hass: HomeAssistant) -> None:
    """Delete the repair issues the integration used to raise and no longer does."""
    for issue_id in _RETIRED_ISSUE_IDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _enable_newly_default_sensors(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Enable the sensors that are now on by default where the integration had disabled them.

    Only an entry whose disabled_by is the integration default qualifies. One the user, the
    config entry or the device disabled is left alone. Once enabled, disabled_by is no longer
    the integration default, so later starts find nothing to do.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    held = {
        e.unique_id.removeprefix(prefix): e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == Platform.SENSOR and e.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    for key in keys_to_enable(held):
        registry.async_update_entity(held[key].entity_id, disabled_by=None)
        _LOG.info("Enabled the sensor %s, which is now on by default", held[key].entity_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service actions and the dashboard strategy once, before any config entry.

    The browser is given the strategy script in the page Home Assistant serves. A page loaded
    while the entry is still setting up, as the browser reloads after a restart, would carry no
    script, so the dashboard failed with "Timeout waiting for strategy element" and the
    Community dashboards entry was missing until a hard refresh. Adding it here puts it in
    every page served from then on, not only those after the entry finished loading.
    """
    await async_register_services(hass)
    try:
        await async_register_strategy(hass)
    except Exception:
        _LOG.exception("Could not register the dashboard strategy")
    return True


async def _announce_dashboard(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Tell the user once how to add the dashboard. A failure here never stops setup."""
    try:
        await async_announce_dashboard(hass, entry)
    except Exception:  # noqa: BLE001 - the notice is a courtesy, not part of setup
        _LOG.exception("Could not tell the user how to add the dashboard")


async def async_setup_entry(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> bool:
    """Set up GivEnergy Inverter Manager from a config entry."""
    _LOG.debug("Setting up entry %s (%s)", entry.entry_id, entry.title)

    _convert_oil_price(hass, entry)
    _warn_about_alt_heat(entry)
    await _announce_dashboard(hass, entry)

    coordinator = GivEnergyCoordinator(hass, entry)

    # Before the first refresh, so the very first snapshot already reads dry run on a test instance.
    await coordinator.async_detect_test_instance()

    # Restore persisted energy accumulators so today/week/month survive HA restarts.
    await coordinator.async_restore_state()

    # Home Assistant raises ConfigEntryNotReady, with the translated UpdateFailed
    # message, when the first refresh fails.
    await coordinator.async_config_entry_first_refresh()
    # A restart inside the cheap window loses the pending retry, so write now if it was missed.
    await coordinator.async_catch_up_charge_write()

    entry.runtime_data = coordinator

    _remove_retired_entities(hass, entry)
    _remove_retired_issues(hass)
    _enable_newly_default_sensors(hass, entry)
    remove_orphaned_entities(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_make_update_listener(entry)))
    # After the platforms, so the first look compares a dashboard built from every entity.
    async_watch_stored_dashboard(hass, entry)

    # async_setup runs once per start; this restores services removed by the last unload.
    await async_register_services(hass)

    try:
        await async_register_strategy(hass)
    except Exception:
        _LOG.exception("Could not register the dashboard strategy")

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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Take down the notice that explains how to add the dashboard, when the last entry goes."""
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        async_dismiss_announcement(hass)


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
