"""Battery health, wear and state sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy

from .. import sensor_values as values
from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Battery health ---
    GivEnergyManagerSensorDescription(
        key="battery_cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycles",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda d: round(d.battery_stats.total_cycles, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="register_write_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="register_write_count",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.register_write_count,
        attrs_fn=values.register_write_attributes,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_cycle_cost_per_kwh",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycle_cost_per_kwh",
        native_unit_of_measurement=CURRENCY_UNIT,
        entity_registry_enabled_default=False,
        value_fn=values.battery_cycle_cost_per_kwh,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_remaining_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_remaining_life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_stats.estimated_remaining_life_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="days_since_full_charge",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="days_since_full_charge",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_stats.days_since_full_charge,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_years_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_years_remaining",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-clock",
        entity_registry_enabled_default=False,
        value_fn=values.battery_years_remaining,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_usable_capacity_kwh",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_usable_capacity_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-heart-outline",
        entity_registry_enabled_default=False,
        value_fn=values.battery_usable_capacity_kwh,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_state",
        translation_key="battery_state",
        icon="mdi:battery-charging-80",
        entity_registry_enabled_default=False,
        value_fn=values.battery_state,
    ),
)
