"""
discovery/__init__.py — Auto-discovery modules for GivEnergy Inverter Manager.
"""
from .ev_charger import (
    ZAPPI_ECO_PLUS_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    discover_ev_chargers,
    update_charger_state,
)
from .forecast import (
    ForecastSensors,
    discover_forecast_sensors,
    discover_immersion_switch_candidates,
)
from .givtcp import givtcp_rate_entity_ids

__all__ = [
    "ZAPPI_ECO_PLUS_MODE",
    "EVCharger",
    "EVChargerBrand",
    "EVChargerState",
    "ForecastSensors",
    "discover_ev_chargers",
    "discover_forecast_sensors",
    "discover_immersion_switch_candidates",
    "givtcp_rate_entity_ids",
    "update_charger_state",
]
