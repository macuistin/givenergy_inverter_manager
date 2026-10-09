"""
base.py — The sensor description type and the helpers that go with it.

Every module in this package builds its descriptions from GivEnergyManagerSensorDescription.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntityDescription

from ..core.devices import Device
from ..core.engine import CoordinatorData

# Sentinel for monetary sensors — actual symbol (€, £, $) resolved at runtime.
CURRENCY_UNIT = "DYNAMIC_CURRENCY"

# Decimals shown for a money total (a cost, earning, bill or saving). A rate per kWh keeps its own.
MONEY_PRECISION = 2


@dataclass(frozen=True, kw_only=True)
class GivEnergyManagerSensorDescription(SensorEntityDescription):
    """Describes a GivEnergy Manager sensor.

    requires names the optional device the sensor needs. The platform creates the sensor
    only while that device is present, so an install without it has no dead entity.
    """

    requires: Device | None = None
    value_fn: Callable[[CoordinatorData], Any] = lambda d: None
    available_fn: Callable[[CoordinatorData], bool] = lambda d: True
    is_daily_total: bool = False  # True: resets at local midnight and exposes last_reset
    reset_period: str | None = None  # "week", "month" or "year" for a longer reset period
    html_fn: Callable[[CoordinatorData], str] | None = None  # the "html" state attribute
    attrs_fn: Callable[[CoordinatorData], dict[str, Any] | None] | None = None  # extra attributes


def reset_period_of(description: GivEnergyManagerSensorDescription) -> str | None:
    """Return "day", "week", "month" or "year" for a sensor that resets, else None."""
    if description.reset_period is not None:
        return description.reset_period
    return "day" if description.is_daily_total else None
