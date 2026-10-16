"""
stored_dashboard_repair.py - raises and clears the dashboard_out_of_date repair.

update_dashboard writes the generated dashboard into a storage dashboard the user picked and
remembers its URL path. This module compares that dashboard with the one the integration would
generate now, and raises the repair while they differ. It looks when Home Assistant has started
(or at setup once it has), a minute after this entry's entities change in the entity registry,
after an options change and once an hour. It never writes a dashboard. Only the action or the
repair's fix does that. The decision is issue_action in core/stored_dashboard.py.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started

from .coordinator import GivEnergyConfigEntry
from .core.stored_dashboard import DashboardFacts, IssueAction, issue_action
from .logging import get_logger
from .repairs import (
    async_create_dashboard_out_of_date_issue,
    async_delete_dashboard_out_of_date_issue,
)
from .services import (
    DASHBOARD_BACKUP_FILENAME,
    async_admin_dashboard,
    async_dashboard_facts,
    forget_stored_dashboard,
    loaded_entries,
    lovelace_is_loaded,
    stored_dashboard_url_path,
)

_LOG = get_logger(__name__)

# Entity registry changes come in bursts (a device added, several entities enabled), so the
# check waits for a quiet minute.
REGISTRY_DEBOUNCE_S = 60
CHECK_INTERVAL = timedelta(hours=1)
_NOTHING = DashboardFacts(exists=False)


def _is_primary(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> bool:
    """True when *entry* is the one the actions use, or will be once its setup ends.

    The first look runs while the entry is still setting up, before it counts as loaded.
    """
    entries = loaded_entries(hass)
    return entries[0] is entry if entries else True


async def async_check_stored_dashboard(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Raise, clear or forget the repair, as issue_action decides.

    Only the entry the actions use looks, because the action remembers the dashboard on it.
    Does nothing while Lovelace is not loaded, because then every dashboard looks missing and
    a remembered one would be forgotten wrongly.
    """
    if not lovelace_is_loaded(hass) or not _is_primary(hass, entry):
        return
    remembered = stored_dashboard_url_path(entry)
    facts = await async_dashboard_facts(hass, remembered) if remembered else _NOTHING
    generated = await async_admin_dashboard(hass, entry) if facts.storage_mode else {}
    _apply(hass, entry, remembered, issue_action(remembered, facts, generated))


def _apply(
    hass: HomeAssistant, entry: GivEnergyConfigEntry, url_path: str, action: IssueAction
) -> None:
    if action is IssueAction.RAISE:
        async_create_dashboard_out_of_date_issue(hass, url_path, DASHBOARD_BACKUP_FILENAME)
        return
    async_delete_dashboard_out_of_date_issue(hass)
    if action is IssueAction.FORGET:
        _LOG.info(
            "The dashboard /%s is gone or not a storage dashboard, so it is no longer kept "
            "up to date",
            url_path,
        )
        forget_stored_dashboard(hass, entry)


async def _async_safe_check(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Run the check from a timer or listener. A failure is logged and never raised."""
    try:
        await async_check_stored_dashboard(hass, entry)
    except Exception:  # noqa: BLE001 - Lovelace internals or the builder; the next check retries
        _LOG.exception("Could not check whether the stored dashboard is up to date")


class _RegistryWatch:
    """Says which entity registry events are about this entry's entities.

    A removed entity is no longer in the registry, so the ids seen are kept to recognise it.
    """

    def __init__(self, hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
        self._hass = hass
        self._entry_id = entry.entry_id
        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        self._ids = {e.entity_id for e in entries}

    @callback
    def concerns_entry(self, event_data: Mapping[str, Any]) -> bool:
        entity_id = event_data["entity_id"]
        entity = er.async_get(self._hass).async_get(entity_id)
        if entity is not None and entity.config_entry_id == self._entry_id:
            self._ids.add(entity_id)
            return True
        return entity_id in self._ids or event_data.get("old_entity_id") in self._ids


@callback
def async_watch_stored_dashboard(hass: HomeAssistant, entry: GivEnergyConfigEntry) -> None:
    """Start the checks for this entry. Everything stops when the entry unloads."""
    debouncer = Debouncer(
        hass,
        logging.getLogger(__name__),
        cooldown=REGISTRY_DEBOUNCE_S,
        immediate=False,
        function=partial(_async_safe_check, hass, entry),
    )
    watch = _RegistryWatch(hass, entry)

    @callback
    def _on_registry_change(_event) -> None:
        debouncer.async_schedule_call()

    async def _on_options_change(hass: HomeAssistant, _entry) -> None:
        await _async_safe_check(hass, entry)

    async def _hourly(_now) -> None:
        await _async_safe_check(hass, entry)

    async def _started(hass: HomeAssistant) -> None:
        await _async_safe_check(hass, entry)

    entry.async_on_unload(debouncer.async_shutdown)
    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _on_registry_change, event_filter=watch.concerns_entry
        )
    )
    entry.async_on_unload(entry.add_update_listener(_on_options_change))
    entry.async_on_unload(async_track_time_interval(hass, _hourly, CHECK_INTERVAL))
    entry.async_on_unload(async_at_started(hass, _started))
    entry.async_on_unload(lambda: async_delete_dashboard_out_of_date_issue(hass))
