"""config.py: the full tariff, and the cost of energy under it."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..timeutil import elapsed_seconds, local_time_on
from .billing import BillBreakdown, money
from .periods import RatePeriod

_AVERAGE_DAYS_PER_MONTH = 30.44


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
        energy = money(energy_cost)
        saving = money(energy_cost * self.discount_rate / 100)
        standing = money(self.standing_charge * days)
        if period_days is not None and period_days > 0:
            share = min(1.0, days / period_days)
        else:
            share = min(1.0, days / _AVERAGE_DAYS_PER_MONTH)
        pso = money(self.pso_levy * share)
        before_vat = money(energy - saving + standing + pso)
        vat = money(before_vat * self.vat_rate / 100)
        export = money(export_credit)
        return BillBreakdown(
            energy=energy,
            supplier_saving=saving,
            standing_charge=standing,
            pso_levy=pso,
            vat=vat,
            export_credit=export,
            total=money(before_vat + vat - export),
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
