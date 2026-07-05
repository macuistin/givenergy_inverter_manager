"""
discovery/__init__.py — Auto-discovery modules for GivEnergy Inverter Manager.
"""
from .ev_charger import (
    ZAPPI_BATTERY_DRAINING_MODES,
    ZAPPI_ECO_PLUS_MODE,
    ZAPPI_STOPPED_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    discover_ev_chargers,
    update_charger_state,
)
from .givtcp import GivTCPInverter, discover_givtcp_inverters, get_suggested_entities

__all__ = [
    "ZAPPI_BATTERY_DRAINING_MODES",
    "ZAPPI_ECO_PLUS_MODE",
    "ZAPPI_STOPPED_MODE",
    "EVCharger",
    "EVChargerBrand",
    "EVChargerState",
    "GivTCPInverter",
    "discover_ev_chargers",
    "discover_givtcp_inverters",
    "get_suggested_entities",
    "update_charger_state",
]
