"""Multi-brand EV charger model, discovery, session tracking and base-rate alert logic."""

from ..guards.alert import AlertAction
from .base_rate import (
    BaseRateReading,
    WatchState,
    WatchStep,
    watch_step,
)
from .defaults import (
    EV_BASE_RATE_ALERT_DELAY_S,
    EV_CHARGER_MIN_POWER_W,
    EV_RECENT_SESSIONS_MAX,
)
from .discover import (
    discover_ev_chargers,
)
from .model import (
    ACTIVE_STATES,
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
from .session import (
    NO_FINISHED_SESSIONS,
    SOLAR_LABEL,
    EVSession,
    EVSessionLog,
    EVSessionStep,
    recent_table,
    track_session,
)
from .state import (
    update_charger_state,
)

__all__ = [
    "ACTIVE_STATES",
    "AlertAction",
    "BaseRateReading",
    "EVCharger",
    "EVChargerBrand",
    "EVChargerState",
    "EVSession",
    "EVSessionLog",
    "EVSessionStep",
    "EV_BASE_RATE_ALERT_DELAY_S",
    "EV_CHARGER_MIN_POWER_W",
    "EV_RECENT_SESSIONS_MAX",
    "FORBIDDEN_MODE_WORDS",
    "NO_FINISHED_SESSIONS",
    "SOLAR_LABEL",
    "SURPLUS_MODE_DEFAULTS",
    "SURPLUS_MODE_NAMES",
    "WatchState",
    "WatchStep",
    "ZAPPI_ECO_PLUS_MODE",
    "ZAPPI_SOLAR_ONLY_MODE",
    "discover_ev_chargers",
    "pick_surplus_mode",
    "recent_table",
    "track_session",
    "update_charger_state",
    "watch_step",
]
