"""Small status sensors: battery direction, integration version and bill period length."""

from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import EntityCategory

from .. import sensor_values as values
from ..const import INTEGRATION_VERSION
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Miscellaneous ---
    GivEnergyManagerSensorDescription(
        key="battery_power_direction",
        translation_key="battery_power_direction",
        icon="mdi:battery-charging",
        entity_registry_enabled_default=False,
        value_fn=values.battery_power_direction,
    ),
    GivEnergyManagerSensorDescription(
        key="integration_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="integration_version",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: INTEGRATION_VERSION,
    ),
    GivEnergyManagerSensorDescription(
        key="days_in_period",
        translation_key="days_in_period",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-start",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.days_in_period,
    ),
)
