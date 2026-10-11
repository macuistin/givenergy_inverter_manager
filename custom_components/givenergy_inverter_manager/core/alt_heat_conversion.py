"""
alt_heat_conversion.py: the one-time move from the oil price options to alternative heating.

Up to 0.17 the oil advice had two options, a price a litre and a sensor for it. Alternative
heating replaces them with an on switch, a label, a unit and a cost (const.py). A home that had
an oil price is converted once, when the entry is set up: the new keys are written with the
label Oil and the unit litre, so the price keeps its meaning and the advice reads as before, and
the old keys are removed. Nothing reads them afterwards.

The conversion runs only while alt_heat_enabled is not saved. Once it is saved, whether true or
false, the entry is left alone. That makes it safe to run on every setup: the second run finds
the saved key and does nothing.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import (
    ALT_HEAT_UNIT_LITRE,
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_ALT_HEAT_ENABLED,
    CONF_ALT_HEAT_LABEL,
    DEFAULT_ALT_HEAT_LABEL,
    LEGACY_OIL_PRICE_ENTITY,
    LEGACY_OIL_PRICE_PER_LITRE,
)

_LEGACY_KEYS = (LEGACY_OIL_PRICE_PER_LITRE, LEGACY_OIL_PRICE_ENTITY)


def _saved(data: Mapping[str, Any], options: Mapping[str, Any], key: str) -> Any:
    """The value in force for *key*, options over data. None and a missing key are unset."""
    value = options.get(key)
    return data.get(key) if value is None else value


def _price(value: Any) -> float | None:
    """A saved price as a positive number, None when it is not one."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def converted_alt_heat(
    data: Mapping[str, Any], options: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The entry data and options after the conversion, None when there is nothing to convert.

    Nothing to convert means alt_heat_enabled is already saved, or neither old key holds a
    price or a sensor. The new keys go in the options, where the options form writes them. The
    old keys are dropped from both, wherever they were.
    """
    if _saved(data, options, CONF_ALT_HEAT_ENABLED) is not None:
        return None
    price = _price(_saved(data, options, LEGACY_OIL_PRICE_PER_LITRE))
    sensor = _saved(data, options, LEGACY_OIL_PRICE_ENTITY) or None
    if price is None and sensor is None:
        return None
    new_options = {k: v for k, v in options.items() if k not in _LEGACY_KEYS}
    new_options.update(
        {
            CONF_ALT_HEAT_ENABLED: True,
            CONF_ALT_HEAT_LABEL: DEFAULT_ALT_HEAT_LABEL,
            CONF_ALT_HEAT_COST_UNIT: ALT_HEAT_UNIT_LITRE,
        }
    )
    if price is not None:
        new_options[CONF_ALT_HEAT_COST] = price
    if sensor is not None:
        new_options[CONF_ALT_HEAT_COST_ENTITY] = sensor
    return {k: v for k, v in data.items() if k not in _LEGACY_KEYS}, new_options
