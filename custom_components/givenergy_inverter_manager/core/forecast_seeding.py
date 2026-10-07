"""Rebuild forecast accuracy records from recorded history. No Home Assistant imports.

The accuracy correction stores one {"forecast", "actual", "clipped"} record a night. A new
install has none, so it waits for several nights. The Home Assistant recorder already holds
the tomorrow forecast sensor and the daily solar counter, and this module pairs them into
the records the nights would have produced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any


@dataclass(frozen=True)
class Reading:
    """One recorded numeric state of a sensor."""

    at: datetime  # timezone aware
    value: float


@dataclass(frozen=True)
class RecordedReadings:
    """What the recorder holds for the two sensors, in any order."""

    forecasts: Sequence[Reading]  # the tomorrow forecast sensor
    solar_totals: Sequence[Reading]  # the GivTCP daily solar counter


def local_midnight(day: date, tz: tzinfo) -> datetime:
    """The first instant of a local calendar day."""
    return datetime.combine(day, time.min, tzinfo=tz)


def query_start(today: date, days: int, tz: tzinfo) -> datetime:
    """Where the recorder query starts, an hour before the first day it needs.

    The recorder gives the state in force at the start of a query, so the first day finds
    the forecast the sensor held before its midnight even when it has not changed since.
    """
    return local_midnight(today - timedelta(days=days), tz) - timedelta(hours=1)


def _forecast_for(day_start: datetime, forecasts: Sequence[Reading]) -> float | None:
    """The last positive forecast recorded before a local midnight.

    The tomorrow sensor holds the forecast for the day that starts at that midnight. A zero
    or negative value is skipped, as the live tracking skips it.
    """
    before = [r for r in forecasts if r.at < day_start and r.value > 0]
    return max(before, key=lambda r: r.at).value if before else None


def _solar_total_of(
    day_start: datetime, day_end: datetime, solar_totals: Sequence[Reading]
) -> float | None:
    """The largest daily counter value recorded during the local day.

    The counter only rises until it resets at midnight, so the maximum is its last value
    of the day and is not thrown by a reading taken just after the reset.
    """
    values = [r.value for r in solar_totals if day_start <= r.at < day_end and r.value >= 0]
    return max(values) if values else None


def seed_forecast_records(
    readings: RecordedReadings, today: date, tz: tzinfo, days: int
) -> list[dict[str, Any]]:
    """Forecast accuracy records for the last `days` completed local days, oldest first.

    A day with no recorded forecast before its midnight, or no daily solar total, is left
    out. The recorder cannot say whether the inverter clipped, so every record carries
    clipped false.
    """
    records: list[dict[str, Any]] = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        day_start = local_midnight(day, tz)
        day_end = local_midnight(day + timedelta(days=1), tz)
        forecast = _forecast_for(day_start, readings.forecasts)
        actual = _solar_total_of(day_start, day_end, readings.solar_totals)
        if forecast is None or actual is None:
            continue
        records.append({"forecast": forecast, "actual": actual, "clipped": False})
    return records
