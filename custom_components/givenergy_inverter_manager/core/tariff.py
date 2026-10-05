"""
tariff.py — Tariff calculation and energy accumulation for GivEnergy Inverter Manager.

Provides:
  RatePeriod      — a single named rate window (e.g. "Nightboost", 02:00–04:00, €0.0965/kWh).
                    Handles overnight periods where end < start (e.g. Night 23:00–08:00).
  TariffConfig    — the full tariff: multiple rate periods, export rate, standing charge,
                    PSO levy, VAT, supplier discount, and bill start day.
                    get_current_rate() returns the cheapest active period so Nightboost
                    always wins over Night when both would match (02:00–04:00).
  EnergyAccumulator — running totals for a billing period: import/export kWh, per-load
                    energy and cost, self-sufficiency %, and net financial position.

All financial calculations apply the discount before VAT, matching how Irish suppliers
(e.g. Electric Ireland) structure their bills.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from datetime import time as dtime
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
)

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
        now_minutes = dt.hour * 60 + dt.minute
        soonest = min(
            cheap,
            key=lambda p: (p.start.hour * 60 + p.start.minute - now_minutes) % 1440,
        )
        delta = (soonest.start.hour * 60 + soonest.start.minute - now_minutes) % 1440
        return round(delta / 60, 2), soonest.start.strftime("%H:%M")

    def get_most_expensive_rate(self) -> RatePeriod:
        """Return the most expensive rate across all periods including the base rate."""
        candidates = list(self.rate_periods) + [self._base_rate_period]
        return max(candidates, key=lambda p: p.rate)

    def calculate_import_cost(self, kwh: float, dt: datetime) -> float:
        """Calculate cost of importing energy at the current rate."""
        rate = self.get_current_rate(dt)
        gross = kwh * rate.rate * (1 - self.discount_rate / 100)
        return gross * (1 + self.vat_rate / 100)

    def calculate_base_rate_cost(self, kwh: float) -> float:
        """Cost of kwh at the base rate with the same discount and VAT as actual imports."""
        gross = kwh * self.base_rate * (1 - self.discount_rate / 100)
        return gross * (1 + self.vat_rate / 100)

    def calculate_export_earnings(self, kwh: float) -> float:
        """Calculate earnings from exporting energy."""
        return kwh * self.export_rate

    def calculate_standing_charges(self, days: int, period_days: int | None = None) -> float:
        """Calculate standing charge and PSO levy including VAT.

        The PSO levy is a flat monthly figure. A full billing period charges it
        once; a part period charges days / period_days of it. Without period_days
        the share is capped at one levy using an average month length.
        """
        gross = self.standing_charge * days
        if period_days is not None and period_days > 0:
            share = min(1.0, days / period_days)
        else:
            share = min(1.0, days / _AVERAGE_DAYS_PER_MONTH)
        return (gross + self.pso_levy * share) * (1 + self.vat_rate / 100)

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
    def self_sufficiency_pct(self) -> float:
        """Percentage of consumption met without grid import."""
        total_consumption = self.house_kwh + self.zappi_kwh + self.immersion_kwh
        if total_consumption == 0:
            return 100.0
        grid_dependent = max(0, total_consumption - self.solar_kwh - self.battery_discharge_kwh)
        return max(0.0, (1 - grid_dependent / total_consumption) * 100)

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
                start=dtime(int(s[0]), int(s[1])),
                end=dtime(int(e[0]), int(e[1])),
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
