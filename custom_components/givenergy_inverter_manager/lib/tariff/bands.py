"""bands.py: which price band each half-hour slot falls in, under a tariff definition.

A slot belongs to the band in force at its start, read on the clock of the definition's time
zone. The slots are real elapsed time, so on a clock-change day a skipped hour has no slots and a
repeated hour is matched twice by the same clock times.

A zone that runs past midnight belongs to the day it starts, so a Friday 23:00 to 08:00 zone
still applies at 01:00 on Saturday. When a public holiday counts as a weekend day, it matches a
zone that lists a weekend day and no zone that lists only weekdays. A zone with no days applies on
every day. Whether a date is a public holiday is not known here, so the caller passes that in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from ..timeutil import shift_real
from .defaults import SLOT_SECONDS
from .definition import TariffDefinition, Zone
from .slots import SlotDay

_WEEKEND = frozenset({5, 6})


def no_holidays(_day: date) -> bool:
    return False


def band_at(
    definition: TariffDefinition,
    moment: datetime,
    is_holiday: Callable[[date], bool] = no_holidays,
) -> str:
    """The name of the band in force at *moment*: the applicable zone of highest priority, or the
    base band."""
    local = moment.astimezone(definition.timezone)
    zones = sorted(definition.import_prices.zones, key=lambda zone: -zone.priority)
    for zone in zones:
        if _applies(zone, local, is_holiday):
            return zone.name
    return definition.import_prices.base.name


def import_by_band(
    days: Sequence[SlotDay],
    definition: TariffDefinition,
    is_holiday: Callable[[date], bool] = no_holidays,
) -> dict[str, Decimal]:
    """kWh imported in each band over *days*, in the order the bands are first met."""
    totals: dict[str, float] = {}
    for day in days:
        for index, kwh in enumerate(day.flows["import"]):
            if kwh:
                start = shift_real(day.start, timedelta(seconds=index * SLOT_SECONDS))
                band = band_at(definition, start, is_holiday)
                totals[band] = totals.get(band, 0.0) + kwh
    return {band: Decimal(repr(round(kwh, 6))) for band, kwh in totals.items()}


def _applies(zone: Zone, local: datetime, is_holiday: Callable[[date], bool]) -> bool:
    if not _in_hours(zone, local.time()):
        return False
    # A zone past midnight belongs to the day it began.
    began = local.date()
    if zone.start > zone.end and local.time() < zone.end:
        began = began - timedelta(days=1)
    if zone.months and began.month not in zone.months:
        return False
    return _on_day(zone, began, is_holiday)


def _in_hours(zone: Zone, clock: time) -> bool:
    if zone.start < zone.end:
        return zone.start <= clock < zone.end
    return clock >= zone.start or clock < zone.end


def _on_day(zone: Zone, day: date, is_holiday: Callable[[date], bool]) -> bool:
    if not zone.days:
        return True
    if zone.holidays_as_weekend and is_holiday(day):
        return bool(zone.days & _WEEKEND)
    return day.weekday() in zone.days
