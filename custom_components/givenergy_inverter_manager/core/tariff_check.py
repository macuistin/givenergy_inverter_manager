"""
tariff_check.py - compare the tariff entered here with the rates GivTCP holds.

GivTCP keeps its own day, night and export rates. The rates entered here always win, and
GivTCP's are shown for comparison only, as attributes of the Current Rate sensor. A GivTCP
rate that is missing, unavailable or not above zero is treated as not held, so an inverter
that never had its rates set shows nothing.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .tariff import TariffConfig


@dataclass(frozen=True)
class GivTCPRates:
    """The rates GivTCP holds. None means the rate is not held or not readable."""

    day: float | None = None
    night: float | None = None
    export: float | None = None

    @property
    def any_held(self) -> bool:
        return any(rate is not None for rate in (self.day, self.night, self.export))


@dataclass(frozen=True)
class RateMismatch:
    """One rate that differs: what this integration uses and what GivTCP holds."""

    label: str
    here: float
    givtcp: float

    @property
    def line(self) -> str:
        return f"{self.label}: {self.here:g} here, {self.givtcp:g} in GivTCP"


def describe_rate_mismatches(mismatches: Sequence[RateMismatch]) -> list[str]:
    """One short line per mismatch, such as "Day rate: 0.3334 here, 0.395 in GivTCP"."""
    return [mismatch.line for mismatch in mismatches]


def find_rate_mismatches(
    tariff: TariffConfig, givtcp: GivTCPRates, tolerance_pct: float
) -> list[RateMismatch]:
    """The GivTCP rates that differ from the tariff by more than *tolerance_pct*.

    The day rate is compared with the base rate and the export rate with the export rate.
    GivTCP has one night rate, so it is compared with the closest timed rate here: a tariff
    with several cheap periods agrees when any one of them matches. A tariff with no timed
    period has no night rate to compare.
    """
    night_here = _closest(tariff.rate_periods, givtcp.night)
    checks = [
        _compare("Day rate", tariff.base_rate, givtcp.day, tolerance_pct),
        _compare("Night rate", night_here, givtcp.night, tolerance_pct),
        _compare("Export rate", tariff.export_rate, givtcp.export, tolerance_pct),
    ]
    return [check for check in checks if check is not None]


def _closest(periods: Sequence, target: float | None) -> float | None:
    """The timed rate nearest *target*, or None when there is no timed rate or no target."""
    if target is None or not periods:
        return None
    return min((period.rate for period in periods), key=lambda rate: abs(rate - target))


def _compare(
    label: str, here: float | None, theirs: float | None, tolerance_pct: float
) -> RateMismatch | None:
    """A mismatch when both rates are above zero and differ by more than the tolerance."""
    if here is None or theirs is None or here <= 0 or theirs <= 0:
        return None
    if abs(here - theirs) / here * 100 <= tolerance_pct:
        return None
    return RateMismatch(label, here, theirs)
