"""
tariff.py: the tariff as the integration stores it, and the dated rate changes.

The tariff model itself (periods, config, accumulator, billing) lives in lib/tariff and is
re-exported here, so existing imports keep working. This module reads the saved options by their
CONF_ keys, which the library never sees: build_tariff turns them into a TariffConfig, and the
dated-change helpers keep the list of changes in the options.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BILL_START_DAY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_PSO_LEVY,
    DEFAULT_RATE_PERIODS,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_VAT_RATE,
    TARIFF_RATE_KEYS,
    TARIFF_REVIEW_STALE_DAYS,
)
from ..lib.tariff import (
    BillBreakdown,
    CounterMemory,
    EnergyAccumulator,
    RatePeriod,
    TariffConfig,
)

__all__ = [
    "BillBreakdown",
    "CounterMemory",
    "EnergyAccumulator",
    "RatePeriod",
    "TariffConfig",
]

_LOG = logging.getLogger(__name__)


def build_tariff(cfg: dict[str, Any]) -> TariffConfig:
    """Build a TariffConfig from a merged config dict."""
    periods: list[RatePeriod] = []
    for p in cfg.get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS):
        try:
            s = p["start"].split(":")
            e = p["end"].split(":")
            period = RatePeriod(
                name=p["name"],
                rate=float(p["rate"]),
                start=time(int(s[0]), int(s[1])),
                end=time(int(e[0]), int(e[1])),
            )
        except (KeyError, ValueError, IndexError) as err:
            _LOG.warning("Skipping malformed rate period %s: %s", p, err)
            continue
        if period.start == period.end:
            _LOG.warning(
                "Skipping rate period %s: start and end are both %s, so it never applies",
                p.get("name"),
                period.start.strftime("%H:%M"),
            )
            continue
        periods.append(period)

    return TariffConfig(
        rate_periods=periods,
        base_rate=float(cfg.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)),
        base_rate_name=str(cfg.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)),
        export_rate=float(cfg.get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE)),
        standing_charge=float(cfg.get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE)),
        pso_levy=float(cfg.get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)),
        vat_rate=float(cfg.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)),
        discount_rate=float(cfg.get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE)),
        bill_start_day=int(cfg.get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY)),
    )


# ── Dated rate changes ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TariffChange:
    """A full set of unit rates that replaces the saved ones from the effective date.

    The set is complete (base rate and name, timed periods, export rate), so the latest
    change in force is applied on its own and never merged with an earlier one.
    """

    effective: date
    rates: dict[str, Any]

    def as_stored(self) -> dict[str, Any]:
        """The JSON-safe dict kept in the config entry options."""
        return {"effective": self.effective.isoformat(), **self.rates}


def _parse_change(entry: Any) -> TariffChange:
    """Read one stored change. Raises KeyError, TypeError or ValueError when it is malformed."""
    effective = date.fromisoformat(str(entry["effective"]))
    rates = {key: entry[key] for key in TARIFF_RATE_KEYS}
    float(rates[CONF_BASE_RATE])
    float(rates[CONF_EXPORT_RATE])
    if not isinstance(rates[CONF_RATE_PERIODS], list):
        raise TypeError("rate_periods must be a list")
    return TariffChange(effective, rates)


def parse_tariff_changes(raw: Any) -> list[TariffChange]:
    """The valid stored changes in date order. A malformed entry is skipped with a warning.

    Two entries for one date keep the later one.
    """
    if not isinstance(raw, list):
        return []
    by_date: dict[date, TariffChange] = {}
    for entry in raw:
        try:
            change = _parse_change(entry)
        except (KeyError, TypeError, ValueError) as err:
            _LOG.warning("Skipping malformed dated tariff change %s: %s", entry, err)
            continue
        by_date[change.effective] = change
    return [by_date[day] for day in sorted(by_date)]


def tariff_in_force(cfg: dict[str, Any], on: date) -> dict[str, Any]:
    """*cfg* with the rates of the latest change effective on or before *on*.

    Returns *cfg* itself when no change applies, so a config with no dated change
    behaves exactly as before.
    """
    due = [c for c in parse_tariff_changes(cfg.get(CONF_TARIFF_CHANGES)) if c.effective <= on]
    return {**cfg, **due[-1].rates} if due else cfg


def scheduled_tariff_changes(cfg: dict[str, Any], on: date) -> list[TariffChange]:
    """The changes that start after *on*, soonest first."""
    return [c for c in parse_tariff_changes(cfg.get(CONF_TARIFF_CHANGES)) if c.effective > on]


def changes_with_scheduled(raw: Any, new: TariffChange) -> list[dict[str, Any]]:
    """The stored changes with *new* added. A change already stored for its date is replaced."""
    kept = [c for c in parse_tariff_changes(raw) if c.effective != new.effective]
    return [c.as_stored() for c in sorted([*kept, new], key=lambda c: c.effective)]


def changes_still_ahead(raw: Any, on: date) -> list[dict[str, Any]]:
    """The stored changes that start after *on*. Used once the saved rates are set by hand,
    when the changes already in force are superseded."""
    return [c.as_stored() for c in parse_tariff_changes(raw) if c.effective > on]


def last_tariff_review(cfg: dict[str, Any]) -> date | None:
    """The day the tariff was last saved changed or confirmed, or None when never recorded."""
    try:
        return date.fromisoformat(str(cfg.get(CONF_TARIFF_REVIEWED_ON)))
    except ValueError:
        return None


def stale_tariff_age_days(cfg: dict[str, Any], today: date) -> int | None:
    """Days since the last tariff review when that is at least the stale limit, else None.

    A tariff with no recorded review is never stale: the coordinator records today first.
    """
    reviewed = last_tariff_review(cfg)
    if reviewed is None:
        return None
    age = (today - reviewed).days
    return age if age >= TARIFF_REVIEW_STALE_DAYS else None


def changes_started(raw: Any, on: date) -> list[dict[str, Any]]:
    """The stored changes that start on or before *on*."""
    return [c.as_stored() for c in parse_tariff_changes(raw) if c.effective <= on]


def _store_changes(options: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    """Keep *changes* in *options*, and leave no key behind when there are none."""
    if changes:
        options[CONF_TARIFF_CHANGES] = changes
    else:
        options.pop(CONF_TARIFF_CHANGES, None)


@dataclass(frozen=True)
class TariffSubmission:
    """What a submitted options form asks for.

    updates          the parsed tariff form values, including the timed rate periods.
    effective        the date the unit rates in *updates* start, or None to apply them now.
    cancel_scheduled drop the changes that have not started yet.
    """

    updates: dict[str, Any]
    effective: date | None = None
    cancel_scheduled: bool = False


def options_after_tariff_save(
    options: dict[str, Any], in_force: dict[str, Any], sub: TariffSubmission, today: date
) -> dict[str, Any]:
    """The options with the submitted tariff applied, now or as a dated change.

    A dated change records only the unit rates. The charges (standing charge, levy, VAT,
    discount, billing day, currency) in the same submission apply now, because one bill
    needs one value of each. Saved rates are untouched, so the old rates stay in force until
    the date. Saving now supersedes the changes already in force and keeps those still ahead.
    The review date moves when the tariff changed or a change was recorded.
    """
    result = dict(options)
    if sub.cancel_scheduled:
        _store_changes(result, changes_started(result.get(CONF_TARIFF_CHANGES), today))
    if sub.effective is not None and sub.effective > today:
        rates = {key: sub.updates[key] for key in TARIFF_RATE_KEYS}
        result.update({k: v for k, v in sub.updates.items() if k not in TARIFF_RATE_KEYS})
        change = TariffChange(sub.effective, rates)
        _store_changes(result, changes_with_scheduled(result.get(CONF_TARIFF_CHANGES), change))
        result[CONF_TARIFF_REVIEWED_ON] = today.isoformat()
        return result
    result.update(sub.updates)
    _store_changes(result, changes_still_ahead(result.get(CONF_TARIFF_CHANGES), today))
    if build_tariff(in_force) != build_tariff({**in_force, **sub.updates}):
        result[CONF_TARIFF_REVIEWED_ON] = today.isoformat()
    return result


def options_after_reconfigure(
    options: dict[str, Any], updates: dict[str, Any], today: date
) -> dict[str, Any]:
    """The options after the reconfigure form saved *updates* to the entry data.

    Options override data, so the saved options for the same keys go, and so do the dated
    changes already in force. Changes still ahead stay. The tariff counts as reviewed today.
    """
    result = {k: v for k, v in options.items() if k not in updates}
    _store_changes(result, changes_still_ahead(result.get(CONF_TARIFF_CHANGES), today))
    result[CONF_TARIFF_REVIEWED_ON] = today.isoformat()
    return result
