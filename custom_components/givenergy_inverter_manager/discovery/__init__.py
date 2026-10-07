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
from .givtcp import (
    UNUSED_SLOT_TIME,
    ActiveChargeSlot,
    GivTCPInverter,
    describe_charge_slots,
    discover_battery_cycle_entities,
    discover_givtcp_inverters,
    find_other_active_charge_slots,
    get_suggested_entities,
    givtcp_rate_entity_ids,
)

__all__ = [
    "UNUSED_SLOT_TIME",
    "ZAPPI_ECO_PLUS_MODE",
    "ActiveChargeSlot",
    "EVCharger",
    "EVChargerBrand",
    "EVChargerState",
    "GivTCPInverter",
    "describe_charge_slots",
    "discover_battery_cycle_entities",
    "discover_ev_chargers",
    "discover_givtcp_inverters",
    "find_other_active_charge_slots",
    "get_suggested_entities",
    "givtcp_rate_entity_ids",
    "update_charger_state",
]
