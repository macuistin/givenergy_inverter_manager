"""model.py: the normalised EV charger, its states and the surplus-only mode rules.

Brand-specific discovery lives in discover.py and the runtime refresh in state.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .defaults import EV_CHARGER_MIN_POWER_W


class EVChargerBrand(StrEnum):
    ZAPPI = "myenergi_zappi"
    WALLBOX = "wallbox"
    OCPP = "ocpp"
    OHME = "ohme"
    EASEE = "easee"
    GIVENERGY = "givenergy_evc"
    GENERIC = "generic"


class EVChargerState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    CHARGING = "charging"
    PAUSED = "paused"
    BOOSTING = "boosting"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


ACTIVE_STATES = (EVChargerState.CHARGING, EVChargerState.BOOSTING)

_DISCOVERED_ENTITY_ATTRS = (
    "power_entity",
    "session_energy_entity",
    "charge_mode_entity",
    "activity_entity",
)

# Maps raw entity states → normalised EVChargerState, per brand
_STATE_MAP: dict[EVChargerBrand, dict[str, EVChargerState]] = {
    EVChargerBrand.ZAPPI: {
        "ev disconnected": EVChargerState.DISCONNECTED,
        "ev connected": EVChargerState.CONNECTED,
        "waiting for ev": EVChargerState.CONNECTED,
        "ev ready to charge": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "diverting": EVChargerState.CHARGING,
        "paused": EVChargerState.PAUSED,
        "boosting": EVChargerState.BOOSTING,
        "completed": EVChargerState.COMPLETED,
        "charging complete": EVChargerState.COMPLETED,
        "stopped": EVChargerState.PAUSED,
        "fault": EVChargerState.UNKNOWN,
    },
    EVChargerBrand.WALLBOX: {
        "disconnected": EVChargerState.DISCONNECTED,
        "waiting": EVChargerState.CONNECTED,
        "locked": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "paused": EVChargerState.PAUSED,
        "ready": EVChargerState.COMPLETED,
        "error": EVChargerState.UNKNOWN,
    },
    EVChargerBrand.OCPP: {
        "available": EVChargerState.DISCONNECTED,
        "preparing": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "suspendedev": EVChargerState.PAUSED,
        "suspendedevse": EVChargerState.PAUSED,
        "finishing": EVChargerState.COMPLETED,
        "reserved": EVChargerState.CONNECTED,
        "unavailable": EVChargerState.UNKNOWN,
    },
    EVChargerBrand.OHME: {
        "unplugged": EVChargerState.DISCONNECTED,
        "plugged in": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "paused": EVChargerState.PAUSED,
        "finished": EVChargerState.COMPLETED,
    },
    EVChargerBrand.EASEE: {
        "disconnected": EVChargerState.DISCONNECTED,
        "awaiting start": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "paused": EVChargerState.PAUSED,
        "completed": EVChargerState.COMPLETED,
        "ready to charge": EVChargerState.CONNECTED,
    },
    # GivTCP's own strings (its evc.py): Connection_Status is "Not Connected" or "Connected", and
    # Charging_State is one of the rest. A failure or an unknown state reads as unknown, so the
    # plug state from Connection_Status stands.
    EVChargerBrand.GIVENERGY: {
        "not connected": EVChargerState.DISCONNECTED,
        "connected": EVChargerState.CONNECTED,
        "idle": EVChargerState.CONNECTED,
        "starting": EVChargerState.CONNECTED,
        "scheduled": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "end of charging": EVChargerState.COMPLETED,
        "unknown": EVChargerState.UNKNOWN,
        "updating": EVChargerState.UNKNOWN,
        "startup failure": EVChargerState.UNKNOWN,
        "system failure": EVChargerState.UNKNOWN,
        "unstable cp": EVChargerState.UNKNOWN,
    },
}

# The brands whose charge mode select has an option that means "use surplus only", and the option
# to use when the select does not say what it offers.
SURPLUS_MODE_DEFAULTS: dict[EVChargerBrand, str] = {
    EVChargerBrand.ZAPPI: "Eco+",
    EVChargerBrand.GIVENERGY: "Solar",
}

# A mode with any of these words in it is never selected, whatever else it says: it stops, pauses
# or forces a charge, or draws from the grid.
FORBIDDEN_MODE_WORDS = ("stop", "off", "pause", "fast", "boost", "grid", "max", "hybrid")
# What "use surplus only" is called, lower case.
SURPLUS_MODE_NAMES = ("eco+", "solar", "surplus", "green")


def pick_surplus_mode(options: Sequence[str]) -> str | None:
    """The option that means "use surplus only", or None when the select offers none.

    An option holding a forbidden word is skipped before it is compared, so a list of stop, fast
    and grid options picks nothing. Hybrid is forbidden too: it takes a constant 6 A from the
    grid, so it is never chosen automatically.
    """
    for option in options:
        lowered = str(option).strip().lower()
        if any(word in lowered for word in FORBIDDEN_MODE_WORDS):
            continue
        if lowered in SURPLUS_MODE_NAMES:
            return str(option)
    return None

# Mode to use when we want to absorb genuine solar surplus (no battery draw)
ZAPPI_ECO_PLUS_MODE = "Eco+"
# Keep this as an alias for any remaining references
ZAPPI_SOLAR_ONLY_MODE = ZAPPI_ECO_PLUS_MODE


@dataclass
class EVCharger:
    """Normalised representation of a discovered EV charger."""

    brand: EVChargerBrand
    name: str
    serial: str
    display_name: str

    # Entity IDs discovered at setup time
    status_entity: str | None = None
    power_entity: str | None = None
    session_energy_entity: str | None = None
    charge_mode_entity: str | None = None  # select entity (Zappi, GivEnergy)
    activity_entity: str | None = None  # operating status (Zappi: Boosting, Diverting, Paused)

    # Runtime state (populated by coordinator each cycle, NOT at discovery)
    state: EVChargerState = EVChargerState.UNKNOWN
    power_w: float = 0.0
    session_kwh: float = 0.0
    charge_mode: str | None = None
    # The options the charge mode select offers, read each cycle. None until it has been read.
    charge_mode_options: tuple[str, ...] | None = None
    is_draining_battery: bool = False

    def normalise_state(self, raw_state: str) -> EVChargerState:
        """Map a raw entity state string to a normalised EVChargerState."""
        brand_map = _STATE_MAP.get(self.brand, {})
        return brand_map.get(raw_state.strip().lower(), EVChargerState.UNKNOWN)

    @property
    def is_drawing_power(self) -> bool:
        """True when the charger reports at least a charging session's minimum power.

        A charger with no power entity cannot say, so it is taken to be drawing.
        """
        return self.power_entity is None or self.power_w >= EV_CHARGER_MIN_POWER_W

    @property
    def is_active(self) -> bool:
        """Delivering energy: the state says so and the charger is drawing power.

        A Zappi keeps a Boosting status while its plug status reads Waiting for EV, so the
        state alone would call a car that is not charging active.
        """
        return self.state in ACTIVE_STATES and self.is_drawing_power

    @property
    def is_plugged_in(self) -> bool:
        return self.state not in (EVChargerState.DISCONNECTED, EVChargerState.UNKNOWN)

    @property
    def is_fully_discovered(self) -> bool:
        """True once the power, session and charge-mode entities have all been found."""
        return None not in (self.power_entity, self.session_energy_entity, self.charge_mode_entity)

    def fill_missing_entities(self, other: EVCharger) -> list[str]:
        """Adopt the entities this charger lacks from a fresh scan of the same charger.

        Keeps the runtime state. Returns the names of the attributes that were filled.
        """
        filled = []
        for attr in _DISCOVERED_ENTITY_ATTRS:
            found = getattr(other, attr)
            if getattr(self, attr) is None and found is not None:
                setattr(self, attr, found)
                filled.append(attr)
        return filled

    @property
    def can_be_paused(self) -> bool:
        """True if we can pause this charger via HA (mode select or switch)."""
        return self.charge_mode_entity is not None

    @property
    def can_set_solar_only_mode(self) -> bool:
        """True if we can switch to a surplus-only mode (Eco+ on a Zappi, Solar on GivEnergy)."""
        return self.brand in SURPLUS_MODE_DEFAULTS and self.charge_mode_entity is not None

    def surplus_mode(self) -> str | None:
        """The mode that means "use surplus only", None when the select offers none.

        From the options the select reports. Before they are read, or when the select reports
        none, it is the brand's own name for it.
        """
        if self.charge_mode_options:
            return pick_surplus_mode(self.charge_mode_options)
        return SURPLUS_MODE_DEFAULTS.get(self.brand)


# Status entities already warned about. Discovery repeats every 5 minutes while the
