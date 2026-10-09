"""
tariff.py — Tariff calculation and energy accumulation for GivEnergy Inverter Manager.

Provides:
  RatePeriod      — a single named rate window (e.g. "Nightboost", 02:00–04:00, €0.0965/kWh).
                    Handles overnight periods where end < start (e.g. Night 23:00–08:00).
  TariffConfig    — the full tariff: multiple rate periods, export rate, standing charge,
                    PSO levy, VAT, supplier discount, and bill start day.
                    get_current_rate() returns the cheapest active period so Nightboost
                    always wins over Night when both would match (02:00–04:00).
  TariffChange    — a new set of unit rates (base, timed periods, export) from an effective date.
                    tariff_in_force() picks the latest change on or before a day, so the old
                    rates apply up to the day before and the new ones from it. Costs already
                    accumulated are never recalculated.
  EnergyAccumulator — running totals for a billing period: import/export kWh, per-load
                    energy and cost, self-sufficiency %, and net financial position.

All financial calculations apply the discount before VAT, matching how Irish suppliers
(e.g. Electric Ireland) structure their bills.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
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
from .timeutil import elapsed_seconds, local_time_on

_LOG = logging.getLogger(__name__)

_AVERAGE_DAYS_PER_MONTH = 30.44


def _money(value: float) -> float:
    """Round to whole cents, halves upward, the way a supplier bill rounds each line."""
    return float(Decimal(repr(round(value, 8))).quantize(Decimal("0.01"), ROUND_HALF_UP))


@dataclass(frozen=True)
class BillBreakdown:
    """One bill, line by line. Every figure is rounded to cents as a bill rounds it."""

    energy: float
    supplier_saving: float
    standing_charge: float
    pso_levy: float
    vat: float
    export_credit: float
    total: float

    @property
    def before_vat(self) -> float:
        return _money(self.energy - self.supplier_saving + self.standing_charge + self.pso_levy)


@dataclass
class RatePeriod:
    """
    A single timed tariff rate period.

    Has explicit start and end times; is_active() returns True within that window.
    Handles overnight spans where end < start (e.g. Night 23:00–08:00).

    The base / daytime rate is NOT a RatePeriod — it is a separate scalar field
    on TariffConfig (base_rate / base_rate_name). This keeps RatePeriod simple
    and the config form clear: one field for the default rate, a list for overrides.
    """

    name: str
    rate: float  # €/kWh
    start: time
    end: time

    def is_active(self, dt: datetime) -> bool:
        """Return True if this period is active at the given datetime."""
        current = dt.time().replace(second=0, microsecond=0)
        if self.start <= self.end:
            # Normal period e.g. 08:00 – 23:00
            return self.start <= current < self.end
        # Overnight period e.g. 23:00 – 08:00
        return current >= self.start or current < self.end


@dataclass
class TariffConfig:
    """
    Full tariff configuration.

    rate_periods  — timed override slots only (Night, Nightboost, etc.).
                    Each overrides the base rate during its window.
    base_rate     — the default rate that applies whenever no timed period is active.
    base_rate_name — display name for the base rate (e.g. "Day").
    """

    rate_periods: list[RatePeriod]
    base_rate: float  # €/kWh — standard daytime / catch-all rate
    base_rate_name: str  # display name for the base rate
    export_rate: float  # €/kWh CEG rate
    standing_charge: float  # €/day
    pso_levy: float  # €/month
    vat_rate: float  # % e.g. 9.0
    discount_rate: float  # % e.g. 5.5
    bill_start_day: int  # day of month billing period starts

    @property
    def _base_rate_period(self) -> RatePeriod:
        """Return the base rate as a RatePeriod for uniform handling."""
        return RatePeriod(self.base_rate_name, self.base_rate, time(0, 0), time(0, 0))

    def get_current_rate(self, dt: datetime) -> RatePeriod:
        """
        Return the rate period that applies at the given datetime.

        Precedence rules:
          1. Among all timed periods that are currently active, the cheapest wins.
             Nightboost (02:00–04:00 at €0.0965) overrides Night (23:00–08:00 at
             €0.1644) automatically — no special-casing needed.
          2. If no timed period is active, the base rate applies.
        """
        active_timed = [p for p in self.rate_periods if p.is_active(dt)]
        if active_timed:
            return min(active_timed, key=lambda p: p.rate)
        return self._base_rate_period

    def get_cheapest_rate(self) -> RatePeriod:
        """Return the cheapest rate across all periods including the base rate."""
        candidates = list(self.rate_periods) + [self._base_rate_period]
        return min(candidates, key=lambda p: p.rate)

    def get_cheapest_rate_start(self) -> time:
        """Return the start time of the cheapest *timed* rate period.

        This is when the coordinator should write the overnight charge target
        to the inverter, so it takes effect as soon as cheap electricity begins.

        Only considers timed periods — the base rate has no meaningful start
        time (its synthetic period uses time(0,0)).  Callers should check
        that rate_periods is non-empty before calling this.
        """
        if not self.rate_periods:
            raise ValueError(
                "get_cheapest_rate_start() called on a flat-rate tariff with no "
                "timed periods. Check tariff.rate_periods before calling."
            )
        return min(self.rate_periods, key=lambda p: p.rate).start

    def next_cheap_rate(self, dt: datetime) -> tuple[float, str | None] | None:
        """Return (hours until a cheaper-than-base period starts, its HH:MM start).

        Returns (0.0, None) when a cheaper-than-base period is active now, and None
        when the tariff has no such period.
        """
        cheap = [p for p in self.rate_periods if p.rate < self.base_rate]
        if not cheap:
            return None
        if any(p.is_active(dt) for p in cheap):
            return 0.0, None
        now = dt.replace(second=0, microsecond=0)
        starts = []
        for period in cheap:
            start = local_time_on(now, period.start)
            if elapsed_seconds(now, start) < 0:
                start = local_time_on(now + timedelta(days=1), period.start)
            starts.append((elapsed_seconds(now, start), period))
        seconds, soonest = min(starts, key=lambda item: item[0])
        return round(seconds / 3600, 2), soonest.start.strftime("%H:%M")

    def calculate_import_cost(self, kwh: float, dt: datetime) -> float:
        """Calculate cost of importing energy at the current rate."""
        rate = self.get_current_rate(dt)
        gross = kwh * rate.rate * (1 - self.discount_rate / 100)
        return gross * (1 + self.vat_rate / 100)

    def effective_import_rate(self, rate: float) -> float:
        """What one kWh costs at this unit rate once the discount and VAT are applied.

        Uses the same two factors as calculate_import_cost, so a price compared with it is
        compared with what the cost sensors charge.
        """
        return rate * (1 - self.discount_rate / 100) * (1 + self.vat_rate / 100)

    def calculate_export_earnings(self, kwh: float) -> float:
        """Calculate earnings from exporting energy."""
        return kwh * self.export_rate

    def energy_cost_from_import_cost(self, import_cost: float) -> float:
        """Reverse the discount and VAT applied to accumulated import cost."""
        factor = (1 - self.discount_rate / 100) * (1 + self.vat_rate / 100)
        return import_cost / factor if factor > 0 else 0.0

    def calculate_bill(
        self,
        energy_cost: float,
        days: int,
        period_days: int | None = None,
        export_credit: float = 0.0,
    ) -> BillBreakdown:
        """Build a bill from energy cost (kWh x rate, before discount and VAT).

        The supplier saving applies to energy only. VAT applies to energy less the
        saving, plus standing charge and PSO levy. The export credit carries no VAT
        and comes off after VAT.
        """
        energy = _money(energy_cost)
        saving = _money(energy_cost * self.discount_rate / 100)
        standing = _money(self.standing_charge * days)
        if period_days is not None and period_days > 0:
            share = min(1.0, days / period_days)
        else:
            share = min(1.0, days / _AVERAGE_DAYS_PER_MONTH)
        pso = _money(self.pso_levy * share)
        before_vat = _money(energy - saving + standing + pso)
        vat = _money(before_vat * self.vat_rate / 100)
        export = _money(export_credit)
        return BillBreakdown(
            energy=energy,
            supplier_saving=saving,
            standing_charge=standing,
            pso_levy=pso,
            vat=vat,
            export_credit=export,
            total=_money(before_vat + vat - export),
        )

    def _bill_start_date(self, year: int, month: int) -> date:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, max(1, min(self.bill_start_day, last_day)))

    def _bill_period_bounds(self, dt: datetime) -> tuple[date, date]:
        """Return (first day of the current period, first day of the next period)."""
        today = dt.date()
        this_start = self._bill_start_date(today.year, today.month)
        if today >= this_start:
            start = this_start
            next_year, next_month = (
                (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            )
            return start, self._bill_start_date(next_year, next_month)
        prev_year, prev_month = (
            (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        )
        return self._bill_start_date(prev_year, prev_month), this_start

    def days_in_bill_period(self, dt: datetime) -> int:
        """Return the total length in days of the billing period containing dt."""
        start, end = self._bill_period_bounds(dt)
        return (end - start).days

    def days_in_current_bill_period(self, dt: datetime) -> int:
        """Return the day number of dt within its billing period.

        The bill start day is day 1, so the result is always at least 1.
        """
        start, _ = self._bill_period_bounds(dt)
        return (dt.date() - start).days + 1

    def days_remaining_in_bill_period(self, dt: datetime) -> int:
        """Return the days left in the billing period after dt's day."""
        return self.days_in_bill_period(dt) - self.days_in_current_bill_period(dt)


@dataclass
class CounterMemory:
    """The last reading of each GivTCP daily counter that feeds the longer periods.

    A daily counter drops to zero at midnight. The memory outlives the midnight reset so a
    stale reading just after it is not added a second time.
    """

    ac_charge_kwh: float = 0.0

    def growth_since_last(self, current_kwh: float) -> float:
        """How far the AC charge counter rose since the last reading, all of it after a reset.

        Remembers current_kwh for the next call.
        """
        rose = current_kwh >= self.ac_charge_kwh
        growth_kwh = current_kwh - self.ac_charge_kwh if rose else current_kwh
        self.ac_charge_kwh = current_kwh
        return growth_kwh


@dataclass
class EnergyAccumulator:
    """
    Tracks energy and cost accumulation over a billing period (resets at midnight).

    Fields are grouped by what they enable:
      Basic flows      — solar, import, export, house, zappi, immersion
      Rate breakdown   — import split by cheap (timed) vs peak (base) rate
      Cost attribution — cost per load type and per rate tier
      Savings          — value delivered by the integration
      Battery health   — throughput for cycle and depreciation tracking
    """

    # ── Basic energy flows ────────────────────────────────────────────────────
    import_kwh: float = 0.0
    export_kwh: float = 0.0
    solar_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    zappi_kwh: float = 0.0
    immersion_kwh: float = 0.0
    house_kwh: float = 0.0
    # The part of import_kwh that went into the battery (GivTCP's AC charge counter). It is
    # stored, not used, so it does not count as the grid supplying the house.
    grid_to_battery_kwh: float = 0.0

    # ── Rate-tier import breakdown ────────────────────────────────────────────
    # "cheap" = any timed rate period active (Night, Nightboost, etc.)
    # "peak"  = base/day rate (no timed period active)
    import_kwh_cheap: float = 0.0  # kWh imported at timed cheap rate
    import_kwh_peak: float = 0.0  # kWh imported at base/peak rate
    import_cost_cheap: float = 0.0  # cost at cheap rate
    import_cost_peak: float = 0.0  # cost at peak rate

    # ── Cost attribution per rate period and load ─────────────────────────────
    import_cost_by_period: dict[str, float] = field(default_factory=dict)
    export_earnings: float = 0.0
    zappi_cost: float = 0.0
    immersion_cost: float = 0.0  # import cost attributable to immersion heater
    house_cost: float = 0.0  # import cost attributable to rest-of-house load

    # ── Counterfactual ────────────────────────────────────────────────────────
    # What the house load would have cost bought from the grid at the rate in force
    # when it ran. The saving from solar and battery is this minus what was paid.
    grid_equivalent_load_cost: float = 0.0

    # ── Integration savings ───────────────────────────────────────────────────
    # immersion_solar_kwh: solar kWh diverted to immersion that would otherwise
    #   have been exported at the lower export rate.
    # immersion_savings:   (import_rate - export_rate) × immersion_solar_kwh
    immersion_solar_kwh: float = 0.0
    immersion_savings: float = 0.0

    # ── Battery throughput ────────────────────────────────────────────────────
    # Total kWh cycled through the battery (in + out). Divide by 2 × capacity
    # to get fractional cycles. Multiply by (replacement_cost / rated_cycles)
    # to estimate depreciation cost.
    battery_throughput_kwh: float = 0.0

    # ── Missed solar (self-consumption opportunity) ───────────────────────────
    # kWh exported while battery is full, solar generating, and no flex load
    # active — represents solar that could have been self-consumed.
    missed_solar_kwh: float = 0.0

    # ── Inverter derating ──────────────────────────────────────────────────────
    # Minutes the inverter spent above the derating temperature threshold today.
    inverter_derating_minutes: float = 0.0

    @property
    def total_import_cost(self) -> float:
        return sum(self.import_cost_by_period.values())

    @property
    def total_cost(self) -> float:
        """Total import cost today (standing charges tracked separately in accrued_bill)."""
        return self.total_import_cost

    @property
    def net_position(self) -> float:
        """Negative = net cost, positive = net earnings."""
        return self.export_earnings - self.total_cost

    @property
    def peak_import_fraction(self) -> float:
        """Fraction of import that occurred at peak (base) rate. 0–1."""
        total = self.import_kwh
        return (self.import_kwh_peak / total) if total > 0 else 0.0

    @property
    def cheap_import_fraction(self) -> float:
        """Fraction of import that occurred at cheap (timed) rate. 0–1."""
        total = self.import_kwh
        return (self.import_kwh_cheap / total) if total > 0 else 0.0

    @property
    def grid_to_house_kwh(self) -> float:
        """Import that went to the house, not into the battery. Never negative.

        Without a grid-to-battery reading the figure is the whole import.
        """
        return max(0.0, self.import_kwh - self.grid_to_battery_kwh)

    @property
    def supplied_without_grid_kwh(self) -> float:
        """The house load not drawn from the grid at the time: solar, and battery discharge."""
        return max(0.0, self.house_kwh - self.grid_to_house_kwh)

    @property
    def self_sufficiency_pct(self) -> float:
        """Percentage of the house's consumption that did not have to be drawn from the grid.

        house_kwh is the whole load, EV and immersion included, so they are not added again.
        Grid energy the battery stored (grid_to_battery_kwh) is not counted against it.
        Later discharge of that stored energy counts as supplied from storage. EV and
        immersion energy bought from the grid is in house_kwh, so it still counts as grid.
        With no grid-to-battery reading, all import counts, as it did before the reading
        existed.
        """
        if self.house_kwh <= 0:
            return 100.0
        return max(0.0, min(100.0, (1 - self.grid_to_house_kwh / self.house_kwh) * 100))

    @property
    def solar_share_pct(self) -> float:
        """Percentage of the house's consumption met by solar generated and kept on site.

        Solar kept on site is generation less export. It includes solar stored in the
        battery, which counts when it is generated, not when it is later discharged.
        It does not count battery discharge, so energy the battery took from the grid
        never raises the figure. It ignores grid import, so buying cheap energy does not
        lower it. Compare self_sufficiency_pct, which counts all the house did not draw from the
        grid.

        house_kwh is the whole load, EV and immersion included, so they are not added again.
        With no consumption the share is 0, not 100 as for self-sufficiency: no solar was
        used, and a day with nothing to power should not read as fully solar powered.
        """
        if self.house_kwh <= 0:
            return 0.0
        solar_kept_kwh = max(0.0, self.solar_kwh - self.export_kwh)
        return min(100.0, solar_kept_kwh / self.house_kwh * 100)

    @property
    def self_consumption_pct(self) -> float:
        """Percentage of solar generation consumed on-site."""
        if self.solar_kwh == 0:
            return 0.0
        return min(100.0, (1 - self.export_kwh / self.solar_kwh) * 100)


# ── Config factory ────────────────────────────────────────────────────────────


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
