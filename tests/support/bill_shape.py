"""A tariff and thirty days of usage shaped like a real bill, for tests that price a bill.

The figures are round, not any supplier's. The tariff library's own tests use the same shape."""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from utility_tariffs_lib.tariff import (
    RatePeriod,
    TariffConfig,
)
from utility_tariffs_lib.tariff.slots import SlotDay

DUBLIN = ZoneInfo("Europe/Dublin")
UTC = timezone.utc


def bill_tariff(**changes) -> TariffConfig:
    """A tariff with the shape of a real bill: two timed bands over a day rate, a saving, a
    monthly levy and VAT. The figures are round, not any supplier's."""
    fields = {
        "rate_periods": [
            RatePeriod("Night", 0.18, time(23, 0), time(8, 0)),
            RatePeriod("Boost", 0.1056, time(2, 0), time(4, 0)),
        ],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 16,
    }
    return TariffConfig(**{**fields, **changes})


# Slot numbers (half hours from midnight) on a day with no clock change.
BOOST = range(4, 8)  # 02:00 to 04:00
NIGHT = [*range(0, 4), *range(8, 16), *range(46, 48)]  # 23:00 to 08:00 except the boost
DAY = range(16, 46)  # 08:00 to 23:00
SOLAR = range(24, 28)


def _spread(day: SlotDay, series: str, slots, kwh: float) -> None:
    for index in slots:
        day.flows[series][index] += kwh / len(slots)
        day.seconds[index] = 1800


def october_bill_days() -> list[SlotDay]:
    """Thirty days, 16 September to 15 October, using 257, 67 and 619 kWh in the three bands
    and exporting 47 kWh, as the meter registers of the bill being checked read."""
    days = []
    for offset in range(30):
        day = SlotDay(date(2026, 9, 16) + timedelta(days=offset), DUBLIN)
        _spread(day, "import", BOOST, 257 / 30)
        _spread(day, "import", NIGHT, 619 / 30)
        _spread(day, "import", DAY, 67 / 30)
        _spread(day, "export", SOLAR, 47 / 30)
        days.append(day)
    return days
