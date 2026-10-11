"""
detect.py - what the system already has, for the setup and options wizards.

The inverter, an EV charger and a forecast sensor are found, used and announced on the first
screen, so they need no page of their own. A wrong guess is fixed in the options wizard. An
immersion switch is only suggested, never applied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.wizard_model import Detected
from ..discovery import (
    discover_ev_chargers,
    discover_forecast_sensors,
    discover_givtcp_inverters,
    discover_immersion_switch_candidates,
)


def detect(states: Mapping[str, Any]) -> Detected:
    """Everything the wizards look for, from the states of the whole system."""
    return Detected(
        inverters=tuple(discover_givtcp_inverters(dict(states))),
        ev_chargers=tuple(discover_ev_chargers(dict(states))),
        forecast=discover_forecast_sensors(states),
        immersion_candidates=discover_immersion_switch_candidates(states),
    )


def best_inverter(detected: Detected) -> Any:
    """The inverter to offer first: one with every required sensor, else the first found."""
    complete = [inverter for inverter in detected.inverters if inverter.is_fully_configured]
    if complete:
        return complete[0]
    return detected.inverters[0] if detected.inverters else None
