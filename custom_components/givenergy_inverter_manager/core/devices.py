"""
devices.py - the optional devices an install can have, and which of them are present.

An install may have no EV charger, no immersion switch and no immersion temperature sensor,
and may gain any of them later. An entity that only makes sense with a device names that
device, so the platforms create it only when the device is present.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from ..const import CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR


class Device(StrEnum):
    """An optional device, named by what makes an entity worth having."""

    EV_CHARGER = "ev_charger"
    IMMERSION_SWITCH = "immersion_switch"
    IMMERSION_SENSOR = "immersion_sensor"
    # The switch and the sensor together. Target, minimum and restart gap only act then.
    IMMERSION_THERMOSTAT = "immersion_thermostat"


def installed_devices(
    config: Mapping[str, Any], *, ev_charger_found: bool
) -> frozenset[Device]:
    """The devices present, from the merged config and whether an EV charger was discovered."""
    switch = bool(config.get(CONF_IMMERSION_SWITCH))
    sensor = bool(config.get(CONF_IMMERSION_TEMP_SENSOR))
    present = {
        Device.EV_CHARGER: ev_charger_found,
        Device.IMMERSION_SWITCH: switch,
        Device.IMMERSION_SENSOR: sensor,
        Device.IMMERSION_THERMOSTAT: switch and sensor,
    }
    return frozenset(device for device, here in present.items() if here)
