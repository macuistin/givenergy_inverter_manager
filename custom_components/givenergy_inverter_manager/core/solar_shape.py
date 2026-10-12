"""
solar_shape.py: the hour-by-hour shape of a solar forecast, as 48 half-hour weights.

The overnight charge simulation spreads the forecast total over the day. By default it uses a
bell curve centred on 13:00. Solcast publishes its own forecast per period (`detailedForecast`
on its forecast sensors: 30-minute periods with `period_start` and `pv_estimate` in kW, and
`detailedHourly` for hourly ones). An east or west facing array, or a day that clouds over at
noon, has a different shape, and the simulation reads the day better with it.

The shape is 48 non-negative weights in local half-hour slots that sum to 1. Periods are mapped on
the local clock, so a clock-change day (46 or 50 real slots) still lands each period in the slot
of its local time: the missing hour of a spring day gets weight 0 and the repeated hour of an
autumn day adds into one slot. Anything that does not look like a day of forecast gives None and
the caller keeps the bell curve.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, tzinfo
from typing import Any

SLOTS = 48
SLOT_MINUTES = 30
# Fewer periods than this cannot be a day of forecast, even hourly ones with the night left out.
_MIN_PERIODS = 12
_ROUND_PLACES = 6


def valid_shape(shape: object) -> tuple[float, ...] | None:
    """The 48 weights normalised to sum to 1, or None when they are not a usable shape."""
    if not isinstance(shape, (list, tuple)) or len(shape) != SLOTS:
        return None
    try:
        weights = tuple(float(w) for w in shape)
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(w) or w < 0 for w in weights):
        return None
    total = sum(weights)
    if total <= 0:
        return None
    return tuple(w / total for w in weights)


def solar_shape_from_periods(
    periods: object, tz: tzinfo, field: str = "pv_estimate"
) -> tuple[float, ...] | None:
    """Turn a provider's list of periods into 48 half-hour weights, or None.

    Each period is a mapping with `period_start` (an ISO string or a datetime) and *field*
    (average power in kW over the period). The period length comes from the gap between starts,
    so a list of hourly periods is not read as half-hours. An hourly period is spread evenly
    over its two slots.
    """
    parsed = _parse(periods, tz, field)
    if parsed is None:
        return None
    length = _period_minutes(sorted({start for start, _ in parsed}))
    if length is None:
        return None
    energy = [0.0] * SLOTS
    spread = length // SLOT_MINUTES
    for start, power in parsed:
        first = start.hour * 2 + start.minute // SLOT_MINUTES
        for offset in range(spread):
            slot = first + offset
            if slot < SLOTS:
                energy[slot] += power / spread
    shape = valid_shape(energy)
    return None if shape is None else tuple(round(w, _ROUND_PLACES) for w in shape)


def _parse(periods: object, tz: tzinfo, field: str) -> list[tuple[datetime, float]] | None:
    if not isinstance(periods, Sequence) or isinstance(periods, (str, bytes)):
        return None
    if len(periods) < _MIN_PERIODS:
        return None
    parsed: list[tuple[datetime, float]] = []
    for period in periods:
        if not isinstance(period, Mapping):
            return None
        start = _start_of(period.get("period_start"), tz)
        power = _power_of(period.get(field))
        if start is None or power is None:
            return None
        parsed.append((start, power))
    return parsed


def _start_of(value: Any, tz: tzinfo) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def _power_of(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        power = float(value)
    except (TypeError, ValueError):
        return None
    return power if math.isfinite(power) and power >= 0 else None


def _period_minutes(starts: list[datetime]) -> int | None:
    """30 or 60, from the smallest gap between starts. None when the gaps say something else."""
    if len(starts) < _MIN_PERIODS:
        return None
    gaps = {(b - a) for a, b in zip(starts, starts[1:], strict=False)}
    smallest = min(gaps)
    for minutes in (SLOT_MINUTES, 2 * SLOT_MINUTES):
        if smallest == timedelta(minutes=minutes):
            return minutes
    return None
