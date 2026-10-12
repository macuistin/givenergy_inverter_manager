"""
detect.py - what the system already has, for the setup and options wizards.

The inverter, an EV charger and a forecast sensor are found, used and announced on the first
screen, so they need no page of their own. A wrong guess is fixed in the options wizard. An
immersion switch is only suggested, never applied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.system_types import Selection, select_controller
from ..core.wizard_model import Detected
from ..discovery import (
    discover_ev_chargers,
    discover_forecast_sensors,
    discover_immersion_switch_candidates,
)
from ..inverter.givtcp.discovery import discover_givtcp_inverters


def detect(states: Mapping[str, Any]) -> Detected:
    """Everything the wizards look for, from the states of the whole system."""
    return Detected(
        inverters=tuple(discover_givtcp_inverters(dict(states))),
        ev_chargers=tuple(discover_ev_chargers(dict(states))),
        forecast=discover_forecast_sensors(states),
        immersion_candidates=discover_immersion_switch_candidates(states),
    )


def selection_of(detected: Detected) -> Selection:
    """Which device the selection rules would manage, and whether they would ask."""
    return select_controller([inverter.facts() for inverter in detected.inverters])


def best_inverter(detected: Detected) -> Any:
    """The inverter to manage: what the selection rules choose, None when none was found."""
    controller = selection_of(detected).controller
    if controller is None:
        return None
    return next(i for i in detected.inverters if i.serial == controller.serial)
