"""
limits.py - battery capacity and inverter output, read from a sensor or typed by the user.

The sensor wins while it reads a usable number. Otherwise the typed value stands, so an
unavailable sensor, a wrong unit or an entry made before sensors were offered all keep working.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

# Factor to the unit the integration uses, by the sensor's own unit text (lower case).
_TO_KWH = {"kwh": 1.0, "wh": 0.001, "mwh": 1000.0}
_TO_KW = {"kw": 1.0, "w": 0.001, "mw": 1000.0}


def _number(state: str | None) -> float | None:
    try:
        value = float(str(state))
    except TypeError, ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def sensor_limit(state: str | None, unit: str | None, factors: Mapping[str, float]) -> float | None:
    """The sensor reading in the integration's unit, None when it is not a usable number."""
    value = _number(state)
    if value is None:
        return None
    factor = factors.get(str(unit or "").strip().lower())
    return value * factor if factor is not None else None


def capacity_kwh(state: str | None, unit: str | None, typed: float) -> float:
    """Battery capacity in kWh. GivTCP publishes kWh and sometimes omits the unit."""
    found = sensor_limit(state, unit or "kWh", _TO_KWH)
    return found if found is not None else typed


def inverter_output_kw(state: str | None, unit: str | None, typed: float) -> float:
    """Inverter maximum output in kW. GivTCP publishes W (for example 5000) and no unit."""
    found = sensor_limit(state, unit or "W", _TO_KW)
    return found if found is not None else typed
