"""Multi-brand EV charger model, discovery, session tracking and base-rate alert logic."""

from .base_rate import (
    AlertAction,
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
from .write_confirmation import (
    ConfirmationStep,
    Unconfirmed,
    UnconfirmedWrite,
    confirmed_step,
    describe_unconfirmed,
    unconfirmed_step,
)

__all__ = [
    "ACTIVE_STATES",
    "AlertAction",
    "BaseRateReading",
    "ConfirmationStep",
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
    "Unconfirmed",
    "UnconfirmedWrite",
    "WatchState",
    "WatchStep",
    "ZAPPI_ECO_PLUS_MODE",
    "ZAPPI_SOLAR_ONLY_MODE",
    "confirmed_step",
    "describe_unconfirmed",
    "discover_ev_chargers",
    "pick_surplus_mode",
    "recent_table",
    "track_session",
    "unconfirmed_step",
    "update_charger_state",
    "watch_step",
]
