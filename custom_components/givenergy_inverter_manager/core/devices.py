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

from ..const import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_ENABLED,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)


class Device(StrEnum):
    """An optional device, named by what makes an entity worth having."""

    EV_CHARGER = "ev_charger"
    IMMERSION_SWITCH = "immersion_switch"
    IMMERSION_SENSOR = "immersion_sensor"
    # The switch and the sensor together. Target, minimum and restart gap only act then.
    IMMERSION_THERMOSTAT = "immersion_thermostat"
    # Alternative water heating switched on with a cost, and the immersion switch. The advice
    # compares the two.
    ALTERNATIVE_HEAT = "alternative_heat"


class DeviceGroup(StrEnum):
    """The Home Assistant device an entity is attached to."""

    MAIN = "main"
    EV_CHARGER = "ev_charger"
    IMMERSION = "immersion"


_GROUPS = {
    Device.EV_CHARGER: DeviceGroup.EV_CHARGER,
    Device.IMMERSION_SWITCH: DeviceGroup.IMMERSION,
    Device.IMMERSION_SENSOR: DeviceGroup.IMMERSION,
    Device.IMMERSION_THERMOSTAT: DeviceGroup.IMMERSION,
}


def group_of(device: Device | None) -> DeviceGroup:
    """The device group for an entity that requires `device`. No requirement means MAIN."""
    return _GROUPS.get(device, DeviceGroup.MAIN) if device else DeviceGroup.MAIN


def alt_heat_configured(config: Mapping[str, Any]) -> bool:
    """True when alternative heating is on and has a cost or a cost sensor.

    The advice also needs the immersion switch to compare with (see installed_devices).
    """
    has_cost = bool(config.get(CONF_ALT_HEAT_COST) or config.get(CONF_ALT_HEAT_COST_ENTITY))
    return bool(config.get(CONF_ALT_HEAT_ENABLED)) and has_cost


def alt_heat_warnings(config: Mapping[str, Any]) -> list[str]:
    """What is missing while alternative heating is on, one line each. Empty when all is set.

    These are warnings, not errors: the setting is kept and the advice starts when the missing
    piece is set.
    """
    if not config.get(CONF_ALT_HEAT_ENABLED):
        return []
    warnings = []
    if not config.get(CONF_IMMERSION_SWITCH):
        warnings.append("no advice until an immersion switch is set")
    if not (config.get(CONF_ALT_HEAT_COST) or config.get(CONF_ALT_HEAT_COST_ENTITY)):
        warnings.append("no advice until a cost is set")
    return warnings


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
        Device.ALTERNATIVE_HEAT: switch and alt_heat_configured(config),
    }
    return frozenset(device for device, here in present.items() if here)
