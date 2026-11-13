"""
shadow_search_steps.py - "find a cheaper plan" in Configure → Shadow tariffs.

  shadow_search           how far back to look (weeks or bills) and an export rate for plans that
                          list none
  shadow_search_results   the ranking, where the current plan stands, and a choice to add one of
                          the plans as a shadow tariff

The search re-prices measured usage under every plan of the current tariff's country and area. It
never changes the active tariff, and a plan is only added as a shadow tariff, which never writes.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from ..const import CONF_BILL_START_DAY, CONF_CURRENCY, CONF_EXPORT_RATE
from ..core.shadow_pricing import config_definition
from ..core.shadow_search import (
    Candidate,
    SearchResult,
    Unit,
    Usage,
    Window,
    ranges,
    rank_sentence,
    search,
)
from ..core.wizard_store import choose_tariff, source_options, source_record
from ..lib.tariff import SlotHistory
from ..shadow_search_store import READ_ERRORS, Gathered, gather
from ..tariff_store import TariffStoreAccess

_LOG = logging.getLogger(__name__)
CURRENT = "current"
LISTED = 10  # plans named in the ranking
OFFERED = 10  # plans offered to add as a shadow tariff


def _number(low: float, high: float, step: float, unit: str | None = None) -> Any:
    config: dict[str, Any] = {"min": low, "max": high, "step": step, "mode": "box"}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(cast("selector.NumberSelectorConfig", config))


def ranking_text(result: SearchResult, symbol: str) -> str:
    """The best plans as a numbered list, the current plan marked, as the bill over the window."""
    rows = []
    for ranked in result.ranked:
        if ranked.rank > LISTED and ranked.key != CURRENT:
            continue
        mark = " (your plan)" if ranked.key == CURRENT else f", {ranked.difference:+.2f}"
        rows.append(f"{ranked.rank}. {ranked.label}: {symbol}{ranked.total:.2f}{mark}")
    return "\n".join(rows)


class ShadowSearchSteps:
    """The search screens. Mixed into the options wizard."""

    hass: Any
    _picked: dict[str, str]

    def _init_search(self) -> None:
        self._search_result: SearchResult
        self._search_found: Gathered
        self._search_export: float = 0.0

    # What the options wizard supplies.
    def _history(self) -> SlotHistory | None:
        raise NotImplementedError  # pragma: no cover

    def _active_config(self) -> dict[str, Any]:
        raise NotImplementedError  # pragma: no cover

    def _active_source(self) -> dict[str, Any] | None:
        raise NotImplementedError  # pragma: no cover

    def _can_add_shadow(self) -> bool:
        raise NotImplementedError  # pragma: no cover

    async def _shadow_finished(self, options: dict[str, Any]) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def async_step_shadow_search(self, user_input: dict[str, Any] | None = None) -> Any:
        """Ask how far back to look, then price every plan."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                return await self._run_search(user_input)
            except ValueError:
                errors["base"] = "search_window"
            except READ_ERRORS as err:
                _LOG.warning("The tariff search could not read the store: %s", err)
                errors["base"] = "search_store"
        config = self._active_config()
        schema = vol.Schema(
            {
                vol.Required("unit", default=Unit.BILLS.value): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[Unit.BILLS.value, Unit.WEEKS.value],
                        translation_key="search_unit",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required("count", default=1): _number(1, 104, 1),
                vol.Required(
                    "export_rate", default=float(config.get(CONF_EXPORT_RATE) or 0)
                ): _number(0, 5, 0.001, str(config.get(CONF_CURRENCY) or "")),
            }
        )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="shadow_search", data_schema=schema, errors=errors
        )

    async def _run_search(self, user_input: dict[str, Any]) -> Any:
        window = Window(Unit(user_input["unit"]), int(user_input["count"]))
        history = self._history()
        config = self._active_config()
        source = self._active_source()
        country = (source or {}).get("country") or getattr(self.hass.config, "country", None)
        through = dt_util.now().date() - timedelta(days=1)
        spans = ranges(window, through, int(config.get(CONF_BILL_START_DAY) or 1))
        if history is None or not country:
            raise ValueError("no history")
        found = await gather(TariffStoreAccess(self.hass), str(country), through, source)
        rate = Decimal(str(user_input["export_rate"]))
        current = Candidate(
            CURRENT, "Your plan", config_definition(config, str(dt_util.get_default_time_zone()))
        )
        others = [Candidate(c.key, c.label, c.definition, rate) for c in found.candidates]
        result = await self.hass.async_add_executor_job(
            search, Usage(history, spans), current, others
        )
        self._search_result, self._search_found = result, found
        self._search_export = float(rate)
        return await self.async_step_shadow_search_results()

    def _offered(self) -> dict[str, str]:
        """The best plans that are not the current one, as {key: label}."""
        result, found = self._search_result, self._search_found
        return {
            r.key: f"{r.rank}. {r.label}"
            for r in result.ranked
            if r.key != CURRENT and r.key in found.places
        }

    async def async_step_shadow_search_results(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """The ranking, and a choice to add one plan as a shadow tariff."""
        result, found = self._search_result, self._search_found
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get("plan"):
            outcome = await self._add_searched(user_input["plan"])
            if outcome is not None:
                return outcome
            errors["base"] = "search_cannot_hold"
        elif user_input is not None:
            return await self.async_step_shadow_menu()  # type: ignore[attr-defined]
        offered = dict(list(self._offered().items())[:OFFERED]) if self._can_add_shadow() else {}
        symbol = str(self._active_config().get(CONF_CURRENCY) or "")
        schema: dict[Any, Any] = (
            {
                vol.Optional("plan"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=k, label=v)
                                 for k, v in offered.items()],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
            if offered
            else {}
        )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="shadow_search_results",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "rank_line": rank_sentence(result),
                "ranking": ranking_text(result, symbol),
                "window": f"{result.first_day:%d %b %Y} to {result.last_day:%d %b %Y}",
                "recorded": f"{result.days_recorded} of {result.days} days",
                "left_out": str(found.other_area + found.unreadable + result.skipped),
            },
        )

    async def _add_searched(self, key: str) -> Any | None:
        """Add the plan as a shadow tariff, or None when the saved rates cannot hold it."""
        found = self._search_found
        place = found.places[key]
        definition = next(c.definition for c in found.candidates if c.key == key)
        config = self._active_config()
        choice = choose_tariff(
            definition, int(config.get(CONF_BILL_START_DAY) or 1), self._search_export
        )
        if not choice.options:
            return None
        record = source_record(place, definition, self._search_export)
        return await self._shadow_finished(source_options(record, choice))


__all__ = ["ShadowSearchSteps", "ranking_text"]
