"""
bill_days.py: one stored row for each finished day of the bill period.

At midnight the day that ended is added to the bill period's list. When the period ends the list
goes into that period's snapshot and the next period starts empty, so the store never holds more
than the current period and the periods already archived. See accumulation.py.

A row holds what the day imported, used and exported in each rate period. The first row of a
period also holds the tariff in force that day, and a later row holds it only when it differs
from the one before, so a tariff that changes mid-bill is recorded on the day it changed and
an archived period keeps the rates it was billed at.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
)
from .tariff import EnergyAccumulator

TARIFF_KEYS = (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_RATE_PERIODS,
    CONF_EXPORT_RATE,
    CONF_STANDING_CHARGE,
    CONF_PSO_LEVY,
    CONF_VAT_RATE,
    CONF_DISCOUNT_RATE,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
)

_DECIMALS = 4


def tariff_snapshot(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The part of the options that prices a bill, as plain data that a row can store."""
    return {key: _plain(cfg[key]) for key in TARIFF_KEYS if key in cfg}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _by_period(values: Mapping[str, float]) -> dict[str, float]:
    return {name: round(kwh, _DECIMALS) for name, kwh in values.items() if kwh}


def day_row(acc: EnergyAccumulator, day: date) -> dict[str, Any]:
    """The row for a finished day, from that day's accumulator."""
    return {
        "date": day.isoformat(),
        "import_kwh": round(acc.import_kwh, _DECIMALS),
        "export_kwh": round(acc.export_kwh, _DECIMALS),
        "solar_kwh": round(acc.solar_kwh, _DECIMALS),
        "house_kwh": round(acc.house_kwh, _DECIMALS),
        "battery_charge_kwh": round(acc.battery_charge_kwh, _DECIMALS),
        "battery_discharge_kwh": round(acc.battery_discharge_kwh, _DECIMALS),
        "import_kwh_by_period": _by_period(acc.import_kwh_by_period),
        "import_cost_by_period": _by_period(acc.import_cost_by_period),
        "house_kwh_by_period": _by_period(acc.house_kwh_by_period),
        "load_cost": round(acc.grid_equivalent_load_cost, _DECIMALS),
        "export_credit": round(acc.export_earnings, _DECIMALS),
    }


def tariff_in_effect(days: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The tariff of the newest row that records one, or None when no row does."""
    for row in reversed(days):
        if isinstance(row.get("tariff"), dict):
            return row["tariff"]
    return None


def with_day(
    days: Sequence[Mapping[str, Any]], row: dict[str, Any], tariff: dict[str, Any]
) -> list[dict[str, Any]]:
    """The list with *row* added, carrying *tariff* when it is the first or differs from before."""
    stored = dict(row)
    if tariff_in_effect(days) != tariff:
        stored["tariff"] = tariff
    return [dict(existing) for existing in days] + [stored]


def tariff_for_day(days: Sequence[Mapping[str, Any]], index: int) -> dict[str, Any] | None:
    """The tariff that applied on the row at *index*: the newest one recorded up to it."""
    return tariff_in_effect(days[: index + 1])


def tariff_changes(days: Sequence[Mapping[str, Any]]) -> list[str]:
    """The dates, after the first row, on which the tariff differs from the day before."""
    return [str(row["date"]) for row in days[1:] if "tariff" in row]
