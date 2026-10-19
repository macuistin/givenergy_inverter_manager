"""Re-export of lib/ev so existing imports keep working. Import from lib/ in new code."""

from ..lib.ev.discover import discover_ev_chargers
from ..lib.ev.model import (
    FORBIDDEN_MODE_WORDS,
    SURPLUS_MODE_DEFAULTS,
    SURPLUS_MODE_NAMES,
    ZAPPI_ECO_PLUS_MODE,
    ZAPPI_SOLAR_ONLY_MODE,
    EVCharger,
    EVChargerBrand,
    EVChargerState,
    pick_surplus_mode,
)
from ..lib.ev.state import update_charger_state

__all__ = [
    "EVCharger",
    "EVChargerBrand",
    "EVChargerState",
    "FORBIDDEN_MODE_WORDS",
    "SURPLUS_MODE_DEFAULTS",
    "SURPLUS_MODE_NAMES",
    "ZAPPI_ECO_PLUS_MODE",
    "ZAPPI_SOLAR_ONLY_MODE",
    "discover_ev_chargers",
    "pick_surplus_mode",
    "update_charger_state",
]
