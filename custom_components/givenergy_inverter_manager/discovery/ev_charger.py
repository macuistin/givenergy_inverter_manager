"""
ev_charger.py — Multi-brand EV charger discovery and battery protection.

Scans Home Assistant entities to find EV chargers from supported integrations
and maps them to a normalised interface. The rest of the integration works with
any charger brand without brand-specific code in the coordinator or optimizer.

Supported integrations and their entity naming conventions:

  myenergi (Zappi)   — sensor.myenergi_zappi_{SERIAL}_plug_status
                       sensor.myenergi_zappi_{SERIAL}_charger_status
                       sensor.myenergi_zappi_{SERIAL}_charge_added_session
                       sensor.myenergi_zappi_{SERIAL}_internal_load_ct1  (power W)
                       select.myenergi_zappi_{SERIAL}_charge_mode
                       Modes: Fast, Eco, Eco+, Stopped

  Wallbox            — sensor.wallbox_{NAME}_status_description
                       sensor.wallbox_{NAME}_charging_power
                       sensor.wallbox_{NAME}_added_energy

  OCPP               — sensor.ocpp_{NAME}_status_connector
                       sensor.ocpp_{NAME}_current_power_import
                       OCPP states: Available, Preparing, Charging,
                       SuspendedEV, SuspendedEVSE, Finishing

  Ohme               — sensor.ohme_{NAME}_status
                       sensor.ohme_{NAME}_power

  Easee              — sensor.easee_{NAME}_status
                       sensor.easee_{NAME}_power

Normalised EV states:
  disconnected — no vehicle plugged in
  connected    — vehicle plugged in, not charging
  charging     — actively delivering energy
  paused       — vehicle plugged in, charging paused
  boosting     — forced/boosted charge in progress
  completed    — session complete
  unknown      — state cannot be determined

─────────────────────────────────────────────────────────────────────────────
IMPORTANT: Zappi Eco+ vs Pause — why we PAUSE rather than switch to Eco+
─────────────────────────────────────────────────────────────────────────────
The Zappi runs autonomously using its own CT clamp — it does NOT read from
GivEnergy. In Eco+ mode the Zappi only charges when it sees net export on
its own CT. This means:

  • At night: the battery naturally discharges to power the house. The Zappi
    CT sees that household consumption and does NOT export, so Eco+ would
    already prevent car charging. But if the Zappi is in Fast mode it will
    happily draw from the battery. The correct response is to set it to
    Stopped (paused), not Eco+.

  • During the day: Eco+ and the GivEnergy battery compete for solar surplus.
    The Zappi CT sees net export and starts charging the car, but that same
    solar could be going into the battery first. The coordinator handles this
    by only un-pausing the Zappi once the battery is above its target SoC,
    then letting Eco+ absorb genuine surplus.

Strategy implemented here:
  1. If battery SoC < protection threshold → set Zappi to Stopped
  2. If battery SoC ≥ protection threshold AND solar surplus is available
     → set Zappi to Eco+ (it will self-regulate on surplus)
  3. For non-Zappi chargers that have no mode select → rely on battery SoC
     reporting via the ev_draining_battery sensor; users must handle manually
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

_LOG = logging.getLogger(__name__)


class EVChargerBrand(StrEnum):
    ZAPPI = "myenergi_zappi"
    WALLBOX = "wallbox"
    OCPP = "ocpp"
    OHME = "ohme"
    EASEE = "easee"
    GENERIC = "generic"


class EVChargerState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    CHARGING = "charging"
    PAUSED = "paused"
    BOOSTING = "boosting"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


# Maps raw entity states → normalised EVChargerState, per brand
_STATE_MAP: dict[EVChargerBrand, dict[str, EVChargerState]] = {
    EVChargerBrand.ZAPPI: {
        "ev disconnected": EVChargerState.DISCONNECTED,
        "ev connected": EVChargerState.CONNECTED,
        "waiting for ev": EVChargerState.CONNECTED,
        "charging": EVChargerState.CHARGING,
        "paused": EVChargerState.PAUSED,
        "boosting": EVChargerState.BOOSTING,
        "completed": EVChargerState.COMPLETED,
        "stopped": EVChargerState.PAUSED,
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
}

# Zappi charge modes that allow drawing from the battery
ZAPPI_BATTERY_DRAINING_MODES = {"fast", "eco"}
# Mode to use when we want to absorb genuine solar surplus (no battery draw)
ZAPPI_ECO_PLUS_MODE = "Eco+"
# Mode to use when we want to completely pause the Zappi
ZAPPI_STOPPED_MODE = "Stopped"
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
    charge_mode_entity: str | None = None  # select entity (Zappi / some others)

    # Runtime state (populated by coordinator each cycle, NOT at discovery)
    state: EVChargerState = EVChargerState.UNKNOWN
    power_w: float = 0.0
    session_kwh: float = 0.0
    charge_mode: str | None = None
    is_draining_battery: bool = False

    def normalise_state(self, raw_state: str) -> EVChargerState:
        """Map a raw entity state string to a normalised EVChargerState."""
        brand_map = _STATE_MAP.get(self.brand, {})
        return brand_map.get(raw_state.strip().lower(), EVChargerState.UNKNOWN)

    @property
    def is_active(self) -> bool:
        return self.state in (EVChargerState.CHARGING, EVChargerState.BOOSTING)

    @property
    def is_plugged_in(self) -> bool:
        return self.state not in (EVChargerState.DISCONNECTED, EVChargerState.UNKNOWN)

    @property
    def can_be_paused(self) -> bool:
        """True if we can pause this charger via HA (mode select or switch)."""
        return self.charge_mode_entity is not None

    @property
    def can_set_solar_only_mode(self) -> bool:
        """True if we can switch to solar-only (Eco+) mode."""
        return self.brand == EVChargerBrand.ZAPPI and self.charge_mode_entity is not None


def _discover_zappi(all_states: dict) -> list[EVCharger]:
    """Discover myenergi Zappi chargers from HA entity states."""
    chargers = []
    for eid in list(all_states):
        if "myenergi_zappi_" not in eid or not eid.startswith("sensor."):
            continue
        if not eid.endswith("_plug_status"):
            continue
        serial = eid.replace("sensor.myenergi_zappi_", "").replace("_plug_status", "")
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name=f"Zappi {serial}",
            serial=serial,
            display_name=f"Zappi ({serial})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.myenergi_zappi_{serial}_internal_load_ct1")
        _maybe(
            ch,
            "session_energy_entity",
            all_states,
            f"sensor.myenergi_zappi_{serial}_charge_added_session",
        )
        _maybe(ch, "charge_mode_entity", all_states, f"select.myenergi_zappi_{serial}_charge_mode")
        if ch.power_entity is None:
            _LOG.warning(
                "%s discovered but power entity not found "
                "— EV kWh will not be tracked until the entity appears.",
                ch.display_name,
            )
        chargers.append(ch)
    return chargers


def _discover_wallbox(all_states: dict) -> list[EVCharger]:
    """Discover Wallbox chargers from HA entity states."""
    chargers = []
    for eid in list(all_states):
        if not eid.startswith("sensor.wallbox_") or not eid.endswith("_status_description"):
            continue
        serial = eid.replace("sensor.wallbox_", "").replace("_status_description", "")
        ch = EVCharger(
            brand=EVChargerBrand.WALLBOX,
            name=f"Wallbox {serial}",
            serial=serial,
            display_name=f"Wallbox ({serial})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.wallbox_{serial}_charging_power")
        _maybe(ch, "session_energy_entity", all_states, f"sensor.wallbox_{serial}_added_energy")
        if ch.power_entity is None:
            _LOG.warning(
                "%s discovered but power entity not found "
                "— EV kWh will not be tracked until the entity appears.",
                ch.display_name,
            )
        chargers.append(ch)
    return chargers


def _discover_ocpp(all_states: dict) -> list[EVCharger]:
    """Discover OCPP chargers from HA entity states."""
    chargers = []
    for eid in list(all_states):
        if not eid.startswith("sensor.ocpp_") or not eid.endswith("_status_connector"):
            continue
        serial = eid.replace("sensor.ocpp_", "").replace("_status_connector", "")
        ch = EVCharger(
            brand=EVChargerBrand.OCPP,
            name=f"OCPP {serial}",
            serial=serial,
            display_name=f"OCPP Charger ({serial})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.ocpp_{serial}_current_power_import")
        if ch.power_entity is None:
            _LOG.warning(
                "%s discovered but power entity not found "
                "— EV kWh will not be tracked until the entity appears.",
                ch.display_name,
            )
        chargers.append(ch)
    return chargers


def _discover_ohme(all_states: dict) -> list[EVCharger]:
    """Discover Ohme chargers from HA entity states."""
    chargers = []
    for eid in list(all_states):
        if not eid.startswith("sensor.ohme_") or not eid.endswith("_status"):
            continue
        if "current_" in eid:
            continue
        serial = eid.replace("sensor.ohme_", "").replace("_status", "")
        ch = EVCharger(
            brand=EVChargerBrand.OHME,
            name=f"Ohme {serial}",
            serial=serial,
            display_name=f"Ohme ({serial})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.ohme_{serial}_power")
        if ch.power_entity is None:
            _LOG.warning(
                "%s discovered but power entity not found "
                "— EV kWh will not be tracked until the entity appears.",
                ch.display_name,
            )
        chargers.append(ch)
    return chargers


def _discover_easee(all_states: dict) -> list[EVCharger]:
    """Discover Easee chargers from HA entity states."""
    chargers = []
    for eid in list(all_states):
        if not eid.startswith("sensor.easee_") or not eid.endswith("_status"):
            continue
        serial = eid.replace("sensor.easee_", "").replace("_status", "")
        ch = EVCharger(
            brand=EVChargerBrand.EASEE,
            name=f"Easee {serial}",
            serial=serial,
            display_name=f"Easee ({serial})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.easee_{serial}_power")
        if ch.power_entity is None:
            _LOG.warning(
                "%s discovered but power entity not found "
                "— EV kWh will not be tracked until the entity appears.",
                ch.display_name,
            )
        chargers.append(ch)
    return chargers


def discover_ev_chargers(all_states: dict) -> list[EVCharger]:
    """
    Scan HA entity states for known EV charger integrations.

    Accepts a dict of {entity_id: state_object} rather than the HA hass object
    so the function is HA-free and testable without a running HA instance.
    The coordinator builds this dict via its _get_all_states() proxy method.

    Returns a list of discovered chargers sorted by brand then serial.
    """
    chargers: list[EVCharger] = []
    for fn in (_discover_zappi, _discover_wallbox, _discover_ocpp, _discover_ohme, _discover_easee):
        chargers.extend(fn(all_states))
    chargers.sort(key=lambda c: (c.brand.value, c.serial))
    return chargers


def _maybe(ch: EVCharger, attr: str, all_states: dict, eid: str) -> None:
    """Set charger attribute only if the entity actually exists in HA."""
    if eid in all_states:
        setattr(ch, attr, eid)


def update_charger_state(
    get_state,
    charger: EVCharger,
    battery_power_w: float,
) -> EVCharger:
    """
    Refresh a charger's runtime state from current HA entity values.

    Accepts a get_state callable (entity_id → state_object | None) rather than
    the HA hass object, keeping this function HA-free and testable. The
    coordinator passes its _get_state() proxy method here.

    Sets is_draining_battery = True when:
      - Charger is actively delivering energy (charging or boosting)
      - Battery is discharging (battery_power_w < -200W, 200W noise floor)

    Mutates and returns the charger object.
    """

    def _read_state(eid: str | None) -> str | None:
        if not eid:
            return None
        s = get_state(eid)
        return s.state if s and s.state not in ("unavailable", "unknown") else None

    def _read_float(eid: str | None) -> float:
        raw = _read_state(eid)
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.0

    raw = _read_state(charger.status_entity)
    if raw is not None:
        charger.state = charger.normalise_state(raw)

    charger.power_w = _read_float(charger.power_entity)
    charger.session_kwh = _read_float(charger.session_energy_entity)

    raw_mode = _read_state(charger.charge_mode_entity)
    if raw_mode is not None:
        charger.charge_mode = raw_mode

    charger.is_draining_battery = charger.is_active and battery_power_w < -200

    return charger
