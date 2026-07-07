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
from datetime import datetime, time
from datetime import time as dtime

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

    def get_most_expensive_rate(self) -> RatePeriod:
        """Return the most expensive rate across all periods including the base rate."""
        candidates = list(self.rate_periods) + [self._base_rate_period]
        return max(candidates, key=lambda p: p.rate)

    def calculate_import_cost(self, kwh: float, dt: datetime | None = None) -> float:
        """Calculate cost of importing energy at the current rate."""
        rate = self.get_current_rate(dt)
        gross = kwh * rate.rate * (1 - self.discount_rate / 100)
        return gross * (1 + self.vat_rate / 100)

    def calculate_export_earnings(self, kwh: float) -> float:
        """Calculate earnings from exporting energy."""
        return kwh * self.export_rate

    def calculate_standing_charges(self, days: int) -> float:
        """Calculate standing charges including VAT."""
        gross = self.standing_charge * days
        pso = self.pso_levy * (days / 30.44)  # pro-rated
        return (gross + pso) * (1 + self.vat_rate / 100)

    def days_in_current_bill_period(self, dt: datetime | None = None) -> int:
        """Return number of days elapsed in the current billing period.

        Returns at least 1 — on the billing start day itself, 1 day has elapsed
        (the period has just begun). This prevents division-by-zero in bill
        projection calculations.
        """
        if dt.day >= self.bill_start_day:
            return max(1, dt.day - self.bill_start_day)
        # We're in the period that started last month
        last_month = dt.month - 1 if dt.month > 1 else 12
        last_month_year = dt.year if dt.month > 1 else dt.year - 1
        days_in_last_month = calendar.monthrange(last_month_year, last_month)[1]
        return max(1, (days_in_last_month - self.bill_start_day) + dt.day)

    def days_remaining_in_bill_period(self, dt: datetime) -> int:
        """Return days remaining in the current billing period."""
        days_in_month = calendar.monthrange(dt.year, dt.month)[1]
        if dt.day < self.bill_start_day:
            return self.bill_start_day - dt.day
        return (days_in_month - dt.day) + self.bill_start_day


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
    import_cost_by_period: dict = field(default_factory=dict)
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


def build_tariff(cfg: dict) -> TariffConfig:
    """Build a TariffConfig from a merged config dict."""
    periods: list[RatePeriod] = []
    for p in cfg.get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS):
        try:
            s = p["start"].split(":")
            e = p["end"].split(":")
            periods.append(
                RatePeriod(
                    name=p["name"],
                    rate=float(p["rate"]),
                    start=dtime(int(s[0]), int(s[1])),
                    end=dtime(int(e[0]), int(e[1])),
                )
            )
        except (KeyError, ValueError, IndexError) as err:
            _LOG.warning("Skipping malformed rate period %s: %s", p, err)

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
