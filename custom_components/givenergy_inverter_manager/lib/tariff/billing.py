"""billing.py: rounding the way a supplier bill rounds, and one bill line by line."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def money(value: float) -> float:
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
        return money(self.energy - self.supplier_saving + self.standing_charge + self.pso_levy)
