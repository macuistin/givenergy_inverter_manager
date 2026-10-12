"""
seasons.py: which months are winter and which are shoulder months for the overnight charge.

In a winter month the battery is charged to 100% whatever the forecast, because solar is
negligible and the grid is the right source. In a shoulder month the minimum charge floor is
raised, because heating load varies and the forecast is less reliable than in summer.

The months follow the seasons of the hemisphere the house is in. They are settings. Until the
user sets them the defaults are worked out from the latitude each time they are read and are
never stored. Winter in the north is December to February and the shoulder months are March,
April, October and November. In the south the same months move by six. Near the equator the
seasons are not designed for, so a user may leave either list empty, which turns that rule off.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..const import (
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
)

_NORTH_WINTER = (12, 1, 2)
_NORTH_SHOULDER = (3, 4, 10, 11)


@dataclass(frozen=True)
class SeasonRules:
    """The winter and shoulder months, and what a winter month does."""

    winter_months: tuple[int, ...] = _NORTH_WINTER
    shoulder_months: tuple[int, ...] = _NORTH_SHOULDER
    # False charges to 100% in winter. True runs the normal plan with the shoulder floor.
    winter_uses_forecast: bool = False


NORTHERN_SEASONS = SeasonRules()


def default_months(latitude: float) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The winter and shoulder months for a latitude: north or on the equator, else shifted six."""
    if latitude >= 0:
        return _NORTH_WINTER, _NORTH_SHOULDER
    return _shift(_NORTH_WINTER), _shift(_NORTH_SHOULDER)


def _shift(months: tuple[int, ...]) -> tuple[int, ...]:
    return tuple((month + 5) % 12 + 1 for month in months)


def season_defaults(latitude: float) -> dict[str, Any]:
    """The two month lists as the configuration holds them, sorted, for a latitude."""
    winter, shoulder = default_months(latitude)
    return {
        CONF_CHARGE_WINTER_MONTHS: sorted(winter),
        CONF_CHARGE_SHOULDER_MONTHS: sorted(shoulder),
    }


def season_rules(cfg: Mapping[str, Any], latitude: float) -> SeasonRules:
    """The rules in force: what the user set, else the defaults for the latitude.

    A saved list, even an empty one, replaces the default. Entries that are not months are
    dropped.
    """
    winter, shoulder = default_months(latitude)
    return SeasonRules(
        winter_months=_months(cfg.get(CONF_CHARGE_WINTER_MONTHS), winter),
        shoulder_months=_months(cfg.get(CONF_CHARGE_SHOULDER_MONTHS), shoulder),
        winter_uses_forecast=bool(cfg.get(CONF_CHARGE_WINTER_USES_FORECAST, False)),
    )


def _months(saved: object, default: tuple[int, ...]) -> tuple[int, ...]:
    if not isinstance(saved, (list, tuple)):
        return default
    months = []
    for item in saved:
        try:
            month = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12:
            months.append(month)
    return tuple(sorted(set(months)))


def overlapping_months(winter: object, shoulder: object) -> list[int]:
    """The months that are in both lists, which the form refuses."""
    return sorted(set(_months(winter, ())) & set(_months(shoulder, ())))
