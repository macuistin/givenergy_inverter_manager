"""
discover.py — Multi-brand EV charger discovery and battery protection.

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

  GivEnergy EVC      — through GivTCP, a device named GivEVC. The prefix is not fixed, so it
                       is found by what it publishes (sensor.{PREFIX}_charging_state,
                       sensor.{PREFIX}_connection_status, sensor.{PREFIX}_active_power,
                       sensor.{PREFIX}_charge_session_energy, select.{PREFIX}_charging_mode).
                       Modes: Grid, Solar, Hybrid

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
Zappi mode control
─────────────────────────────────────────────────────────────────────────────
The Zappi runs autonomously using its own CT clamp and does not read from
GivEnergy. The integration only ever selects Eco+ (never Stopped or Fast), and
only when a vehicle is plugged in and the net solar surplus is at least
EV_CHARGER_MIN_POWER_W. Eco+ then self-regulates on the surplus the Zappi CT sees.

A GivEnergy charger is set the same way. Its logical mode "use surplus only" is Solar.
The integration never selects Grid, never uses Charge Control to stop a session, never turns
Plug and Go off, and never selects Hybrid, which draws a constant 6 A from the grid. See
pick_surplus_mode: a charger whose mode select offers no surplus-only option is left alone.

For chargers with no mode select, the ev_draining_battery sensor reports battery
discharge and users must act on it themselves.
"""

from __future__ import annotations

import logging
from typing import Any

from .model import EVCharger, EVChargerBrand

_LOG = logging.getLogger(__name__)

def _warn_if_power_missing(ch: EVCharger, warned: set[str] | None) -> None:
    """Log once per charger when its power entity was not found.

    *warned* is the caller's memory of what it has already logged. Without it nothing is logged,
    so a one-off scan (setup, the optional-device check) stays quiet.
    """
    if warned is None:
        return
    key = ch.status_entity or ch.display_name
    if ch.power_entity is not None:
        warned.discard(key)
        return
    if key in warned:
        return
    warned.add(key)
    _LOG.warning(
        "%s discovered but power entity not found "
        "— EV kWh will not be tracked until the entity appears.",
        ch.display_name,
    )


def _discover_zappi(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
    """Discover myenergi Zappi chargers from HA entity states.

    The myenergi integration names entities `sensor.myenergi_zappi_<serial>_plug_status`
    when the device name includes the serial and `sensor.myenergi_zappi_plug_status`
    when it does not. Every related entity shares the prefix of the plug status entity.
    """
    chargers = []
    for eid in list(all_states):
        if "myenergi_zappi_" not in eid or not eid.startswith("sensor."):
            continue
        if not eid.endswith("_plug_status"):
            continue
        prefix = eid[: -len("plug_status")]
        serial = prefix.replace("sensor.myenergi_zappi_", "").strip("_")
        if not serial:
            serial_state = all_states.get("sensor.myenergi_zappi_serial_number")
            serial = (
                getattr(serial_state, "state", "") or "" if serial_state is not None else ""
            ).strip()
            if serial in ("unknown", "unavailable"):
                serial = ""
        label = serial or "myenergi"
        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name=f"Zappi {label}",
            serial=serial,
            display_name=f"Zappi ({label})",
            status_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"{prefix}internal_load_ct1")
        _maybe(ch, "session_energy_entity", all_states, f"{prefix}charge_added_session")
        _maybe(
            ch,
            "charge_mode_entity",
            all_states,
            prefix.replace("sensor.", "select.", 1) + "charge_mode",
        )
        _maybe(ch, "activity_entity", all_states, f"{prefix.rstrip('_')}_status".replace("__", "_"))
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def _discover_wallbox(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
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
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def _discover_ocpp(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
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
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def _discover_ohme(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
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
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def _discover_easee(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
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
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def _discover_givenergy_evc(all_states: dict[str, Any], warned: set[str] | None) -> list[EVCharger]:
    """Discover GivEnergy chargers published by GivTCP, by what the device publishes.

    GivTCP names the device GivEVC and lets the user change the prefix, so the prefix is taken
    from the charging state sensor, and the connection status sensor must be there too. The
    inverter's own discovery ignores the device because it has no state of charge.
    """
    suffix = "_charging_state"
    chargers = []
    for eid in list(all_states):
        if not eid.startswith("sensor.") or not eid.endswith(suffix):
            continue
        prefix = eid[len("sensor.") : -len(suffix)]
        if f"sensor.{prefix}_connection_status" not in all_states:
            continue
        serial_state = all_states.get(f"sensor.{prefix}_serial_number")
        serial = str(getattr(serial_state, "state", "") or "").strip()
        if serial.lower() in ("", "unknown", "unavailable"):
            serial = prefix.rsplit("_", 1)[-1].upper()
        ch = EVCharger(
            brand=EVChargerBrand.GIVENERGY,
            name=f"GivEnergy EVC {serial}",
            serial=serial,
            display_name=f"GivEnergy EVC ({serial})",
            status_entity=f"sensor.{prefix}_connection_status",
            activity_entity=eid,
        )
        _maybe(ch, "power_entity", all_states, f"sensor.{prefix}_active_power")
        _maybe(ch, "session_energy_entity", all_states, f"sensor.{prefix}_charge_session_energy")
        _maybe(ch, "charge_mode_entity", all_states, f"select.{prefix}_charging_mode")
        _warn_if_power_missing(ch, warned)
        chargers.append(ch)
    return chargers


def discover_ev_chargers(
    all_states: dict[str, Any], warned: set[str] | None = None
) -> list[EVCharger]:
    """
    Scan HA entity states for known EV charger integrations.

    Accepts a dict of {entity_id: state_object} rather than the HA hass object
    so the function is HA-free and testable without a running HA instance.
    The coordinator builds this dict via its _get_all_states() proxy method.

    *warned* holds the chargers already reported as having no power entity. The caller keeps it
    between scans, so the warning is logged once per charger. Without it nothing is logged.

    Returns a list of discovered chargers sorted by brand then serial.
    """
    chargers: list[EVCharger] = []
    for fn in (
        _discover_zappi,
        _discover_wallbox,
        _discover_ocpp,
        _discover_ohme,
        _discover_easee,
        _discover_givenergy_evc,
    ):
        chargers.extend(fn(all_states, warned))
    chargers.sort(key=lambda c: (c.brand.value, c.serial))
    return chargers


def _maybe(ch: EVCharger, attr: str, all_states: dict[str, Any], eid: str) -> None:
    """Set charger attribute only if the entity actually exists in HA."""
    if eid in all_states:
        setattr(ch, attr, eid)
