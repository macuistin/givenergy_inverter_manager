"""
alt_heat_cost.py: the cost of one kWh of heat from the alternative water heating.

The setting holds a cost and the unit it is quoted in:

  * litre: the price of a litre of heating oil. A litre gives OIL_KWH_PER_LITRE of energy and
    the boiler delivers OIL_BOILER_EFFICIENCY_PCT of it to the water, both fixed assumptions.
  * kwh_heat: the cost of one kWh of heat delivered to the water, efficiency already included.
    A gas boiler is the gas price per kWh over its efficiency. A heat pump is the electricity
    rate over its coefficient of performance.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from ..const import ALT_HEAT_UNIT_KWH_HEAT, OIL_BOILER_EFFICIENCY_PCT, OIL_KWH_PER_LITRE


def litre_heat_cost_per_kwh(price_per_litre: float) -> float:
    """The cost of one kWh of heat from oil at this price a litre."""
    if price_per_litre < 0:
        raise ValueError("the oil price cannot be negative")
    return price_per_litre / (OIL_KWH_PER_LITRE * OIL_BOILER_EFFICIENCY_PCT / 100)


def heat_cost_per_kwh(unit: object, cost: float) -> float:
    """The cost of one kWh of heat, from *cost* quoted in *unit*.

    An unknown unit reads as the default (a litre), so a hand-edited entry cannot stop the
    advice. A negative cost is an error.
    """
    if cost < 0:
        raise ValueError("the cost cannot be negative")
    if unit == ALT_HEAT_UNIT_KWH_HEAT:
        return cost
    return litre_heat_cost_per_kwh(cost)
