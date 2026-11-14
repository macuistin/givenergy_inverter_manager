"""
shadow_ranker.py - keeps the ranking of every store plan against the current tariff up to date.

Once at start-up and once a day, shortly after the day's usage is final, every plan of the current
tariff's country and area is priced over the last whole bill (`lib/tariffranking`) and the
ranking is kept for the sensors and the dashboard. It re-prices measured usage and writes nothing,
and it never changes the active tariff. A store that cannot be read, or too little history, leaves
the last ranking in place.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .conf import CONF_BILL_START_DAY, CONF_EXPORT_RATE, CONF_TARIFF_SOURCE
from .config_helpers import effective_config
from .core.shadow_pricing import config_definition
from .core.shadow_ranking import CURRENT, WINDOW, PlanRanking, summarise
from .lib.tariff import SlotHistory
from .lib.tariffranking import Candidate, Usage, needs_export_rate, ranges, search
from .shadow_search_store import READ_ERRORS, gather
from .tariff_store import TariffStoreAccess

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOG = logging.getLogger(__name__)
RANK_HOUR = 0
RANK_MINUTE = 30  # after the midnight reset has closed the day


class ShadowRanker:
    """Holds the latest ranking. `history` is read fresh each time it refreshes."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, history: Callable[[], SlotHistory | None]
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._history = history
        self.ranking: PlanRanking | None = None

    async def async_refresh(self, today: date, tz: str) -> PlanRanking | None:
        """Price every plan again. Returns the new ranking, or None when none could be made."""
        cfg = effective_config(self._entry)
        source = cfg.get(CONF_TARIFF_SOURCE) or None
        country = (source or {}).get("country") or getattr(self._hass.config, "country", None)
        history = self._history()
        if history is None or not country:
            return None
        store = TariffStoreAccess(self._hass)
        through = today - timedelta(days=1)
        try:
            await store.async_refresh()
            found = await gather(store, str(country), through, source)
        except READ_ERRORS as err:
            _LOG.debug("The plan ranking could not read the store: %s", err)
            return None
        return await self._rank(cfg, found, (history, through, tz))

    async def _rank(
        self, cfg: dict[str, Any], found: Any, usage: tuple[Any, date, str]
    ) -> PlanRanking:
        history, through, tz = usage
        rate = Decimal(str(cfg.get(CONF_EXPORT_RATE) or 0))
        current = Candidate(CURRENT, "Your plan", config_definition(cfg, tz))
        others = [Candidate(c.key, c.label, c.definition, rate) for c in found.candidates]
        spans = ranges(WINDOW, through, int(cfg.get(CONF_BILL_START_DAY) or 1))
        result = await self._hass.async_add_executor_job(
            search, Usage(history, spans), current, others
        )
        assumed = sum(1 for c in others if needs_export_rate(c.definition))
        left_out = found.other_area + found.unreadable + result.skipped
        self.ranking = summarise(result, left_out, assumed)
        return self.ranking


def _task(hass: HomeAssistant, entry: ConfigEntry, ranker: ShadowRanker) -> None:
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    async def run() -> None:
        try:
            await ranker.async_refresh(dt_util.now().date(), str(dt_util.get_default_time_zone()))
        except (ValueError, OSError, KeyError, TypeError) as err:
            _LOG.warning("The plan ranking could not be worked out: %s", err)

    entry.async_create_background_task(hass, run(), "givenergy plan ranking")


def async_rank_at_start(hass: HomeAssistant, entry: ConfigEntry, ranker: ShadowRanker) -> None:
    """Rank once now, in the background."""
    _task(hass, entry, ranker)


def async_track_daily_ranking(
    hass: HomeAssistant, entry: ConfigEntry, ranker: ShadowRanker
) -> None:
    """Rank every day at 00:30 local time, until the entry unloads."""
    from homeassistant.core import callback  # noqa: PLC0415
    from homeassistant.helpers.event import async_track_time_change  # noqa: PLC0415

    @callback
    def daily(_now: object) -> None:
        _task(hass, entry, ranker)

    entry.async_on_unload(
        async_track_time_change(hass, daily, hour=RANK_HOUR, minute=RANK_MINUTE, second=0)
    )
