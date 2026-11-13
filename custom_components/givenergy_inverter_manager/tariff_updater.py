"""
tariff_updater.py - keeps a tariff chosen from the store up to date.

Once a day, shortly after midnight, and once at start-up, the saved tariff is read from the store
again (`core/tariff_update.py` decides what that means). A newer revision in force is copied into
the saved options whole. The check runs after the midnight reset (00:00:00), which prices the day
that just ended from the saved options, so the old revision prices that day.

Nothing leaves the install except the static file paths of the followed tariff. A store that cannot
be read changes nothing and raises nothing: the saved rates keep working.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from .conf import CONF_BILL_START_DAY, CONF_TARIFF_SOURCE
from .config_helpers import effective_config
from .core.tariff_update import Outcome, UpdateDecision, decide, ended, follows_store
from .repairs import (
    async_create_tariff_needs_attention_issue,
    async_create_tariff_update_available_issue,
    async_delete_tariff_update_issues,
)
from .tariff_store import StoreError, TariffStoreAccess

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOG = logging.getLogger(__name__)
NOTIFICATION_PREFIX = "givenergy_inverter_manager_tariff_updated"
UPDATE_HOUR = 0
UPDATE_MINUTE = 5  # after the midnight reset has priced the finished day
STORE_ERRORS = (StoreError, OSError, ValueError, KeyError, TypeError)


async def _read_decision(
    store: TariffStoreAccess, cfg: dict[str, Any], today: date
) -> UpdateDecision | None:
    """What the store says about the followed tariff, or None when it could not be read."""
    record = cfg[CONF_TARIFF_SOURCE]
    where = (record["country"], record["provider"], record["tariff"])
    try:
        listed = await store.async_tariffs(where[0], where[1], today)
    except STORE_ERRORS as err:
        _LOG.debug("The tariff store could not be read: %s", err)
        return None
    if where[2] not in listed:
        return ended(record)
    try:
        definition = await store.async_definition(*where, today, area=record["area"])
    except STORE_ERRORS as err:
        _LOG.debug("The followed tariff could not be read: %s", err)
        return None
    return decide(record, definition, cfg, int(cfg.get(CONF_BILL_START_DAY, 1)))


def _announce_update(hass: HomeAssistant, entry: ConfigEntry, record: dict[str, Any]) -> None:
    from homeassistant.components import persistent_notification  # noqa: PLC0415

    persistent_notification.async_create(
        hass,
        f"{record['provider_name']} {record['name']} has new prices from "
        f"{record['effective_from']}. Your saved rates now use them.",
        title="Tariff prices updated",
        notification_id=f"{NOTIFICATION_PREFIX}_{entry.entry_id}",
    )


def _apply(hass: HomeAssistant, entry: ConfigEntry, decision: UpdateDecision) -> None:
    options = {**entry.options, **decision.options, CONF_TARIFF_SOURCE: decision.record}
    hass.config_entries.async_update_entry(entry, options=options)
    _announce_update(hass, entry, decision.record)
    _LOG.info("Applied the new tariff prices from %s", decision.record["effective_from"])


def _label(record: dict[str, Any]) -> str:
    return f"{record['provider_name']} {record['name']}"


def _show(hass: HomeAssistant, entry: ConfigEntry, decision: UpdateDecision) -> None:
    record = effective_config(entry)[CONF_TARIFF_SOURCE]
    if decision.outcome is Outcome.APPLY:
        async_delete_tariff_update_issues(hass)
        _apply(hass, entry, decision)
    elif decision.outcome is Outcome.OFFER:
        async_create_tariff_update_available_issue(
            hass, _label(record), decision.record["effective_from"]
        )
    elif decision.outcome is Outcome.ATTENTION:
        async_create_tariff_needs_attention_issue(
            hass, _label(record), "; ".join(decision.reasons)
        )
    else:
        async_delete_tariff_update_issues(hass)


async def async_check_tariff(
    hass: HomeAssistant, entry: ConfigEntry, store: TariffStoreAccess, today: date
) -> UpdateDecision | None:
    """Look at the store once and act. Returns what was decided, None when nothing was read."""
    cfg = effective_config(entry)
    if not follows_store(cfg.get(CONF_TARIFF_SOURCE)):
        async_delete_tariff_update_issues(hass)
        return None
    await store.async_refresh()
    decision = await _read_decision(store, cfg, today)
    if decision is not None:
        _show(hass, entry, decision)
    return decision


def async_start_tariff_updates(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Check once now, then every day at 00:05 local time, until the entry unloads."""
    from homeassistant.core import callback  # noqa: PLC0415
    from homeassistant.helpers.event import async_track_time_change  # noqa: PLC0415
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    store = TariffStoreAccess(hass)

    async def check() -> None:
        await async_check_tariff(hass, entry, store, dt_util.now().date())

    @callback
    def daily(_now: object) -> None:
        entry.async_create_background_task(hass, check(), "givenergy tariff update")

    entry.async_on_unload(
        async_track_time_change(hass, daily, hour=UPDATE_HOUR, minute=UPDATE_MINUTE, second=0)
    )
    entry.async_create_background_task(hass, check(), "givenergy tariff update")
