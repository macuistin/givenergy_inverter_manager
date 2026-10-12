"""Dry run, charge floor, inverter temperature and carbon intensity sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature

from .. import sensor_values as values
from ..core.controller_conflict import STATE_NONE, STATE_SUSPECTED
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    GivEnergyManagerSensorDescription(
        key="dry_run_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_active",
        icon="mdi:test-tube",
        attrs_fn=values.dry_run_attributes,
        value_fn=lambda d: d.dry_run,
    ),
    GivEnergyManagerSensorDescription(
        key="cheap_rate_floor_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="cheap_rate_floor_status",
        icon="mdi:battery-arrow-up",
        value_fn=lambda d: d.cheap_rate_floor_status or "Inactive",
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_temperature",
        translation_key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=values.inverter_temperature,
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_temperature_status",
        translation_key="inverter_temperature_status",
        value_fn=lambda d: d.inverter_temperature_status,
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_derating_today_minutes",
        translation_key="inverter_derating_today_minutes",
        state_class=SensorStateClass.TOTAL,
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.inverter_derating_minutes, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="carbon_intensity",
        translation_key="carbon_intensity",
        native_unit_of_measurement="g CO2/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:molecule-co2",
        entity_registry_enabled_default=False,
        value_fn=values.carbon_intensity,
    ),
    GivEnergyManagerSensorDescription(
        key="carbon_intensity_status",
        translation_key="carbon_intensity_status",
        icon="mdi:leaf",
        entity_registry_enabled_default=False,
        value_fn=values.carbon_intensity_status,
    ),
    GivEnergyManagerSensorDescription(
        key="setup_progress",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="setup_progress",
        icon="mdi:clipboard-check-outline",
        attrs_fn=values.setup_progress_attributes,
        value_fn=values.setup_progress_state,
    ),
    GivEnergyManagerSensorDescription(
        key="charge_target_conflict",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="charge_target_conflict",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_NONE, STATE_SUSPECTED],
        icon="mdi:swap-horizontal-bold",
        attrs_fn=values.charge_target_conflict_attributes,
        value_fn=values.charge_target_conflict_state,
    ),
    GivEnergyManagerSensorDescription(
        key="dry_run_last_skipped",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_last_skipped",
        icon="mdi:skip-next-circle-outline",
        value_fn=lambda d: d.dry_run_last_skipped or "No actions skipped yet",
    ),
)
