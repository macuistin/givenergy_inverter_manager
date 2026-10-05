"""
sensor_descriptions — The sensor description table, split by theme.

Each module holds one themed run of descriptions. SENSOR_DESCRIPTIONS joins them in the
order below, which is the order of the entities in the registry and in docs/sensors.md.
"""

from __future__ import annotations

from . import (
    battery,
    bill,
    decisions,
    diagnostics,
    forecast,
    loads,
    month_and_year,
    power,
    reports,
    status,
    tariff,
    today,
    today_breakdown,
    week,
    yesterday,
)
from .base import GivEnergyManagerSensorDescription

SENSOR_DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    *power.DESCRIPTIONS,
    *tariff.DESCRIPTIONS,
    *today.DESCRIPTIONS,
    *bill.DESCRIPTIONS,
    *battery.DESCRIPTIONS,
    *decisions.DESCRIPTIONS,
    *loads.DESCRIPTIONS,
    *diagnostics.DESCRIPTIONS,
    *today_breakdown.DESCRIPTIONS,
    *forecast.DESCRIPTIONS,
    *yesterday.DESCRIPTIONS,
    *week.DESCRIPTIONS,
    *month_and_year.DESCRIPTIONS,
    *reports.DESCRIPTIONS,
    *status.DESCRIPTIONS,
)
