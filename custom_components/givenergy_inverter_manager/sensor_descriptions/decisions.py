"""Outputs of the decision rules: overnight charge, immersion divert, night survival, clipping."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .. import sensor_values as values
from .base import CURRENCY_UNIT, MONEY_PRECISION, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Overnight charge decision ---
    GivEnergyManagerSensorDescription(
        key="overnight_charge_target",
        translation_key="overnight_charge_target",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=values.overnight_charge_target,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_reason",
        attrs_fn=values.forecast_accuracy_attributes,
        value_fn=values.overnight_charge_reason,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_window",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_window",
        icon="mdi:clock-time-four-outline",
        attrs_fn=values.overnight_charge_window_attributes,
        value_fn=values.overnight_charge_window,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_cost",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_cost",
        native_unit_of_measurement=CURRENCY_UNIT,
        suggested_display_precision=MONEY_PRECISION,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        value_fn=values.overnight_charge_cost,
    ),
    # --- Immersion divert ---
    GivEnergyManagerSensorDescription(
        key="immersion_divert_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="immersion_divert_reason",
        value_fn=lambda d: d.divert_reason,
    ),
    # --- Night survival ---
    GivEnergyManagerSensorDescription(
        key="estimated_soc_at_sunrise",
        translation_key="estimated_soc_at_sunrise",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.estimated_soc_at_sunrise, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="night_survival_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="night_survival_reason",
        value_fn=lambda d: d.survival_reason,
    ),
    GivEnergyManagerSensorDescription(
        key="night_survival_confidence",
        translation_key="night_survival_confidence",
        icon="mdi:moon-waning-crescent",
        entity_registry_enabled_default=False,
        attrs_fn=values.night_survival_attributes,
        value_fn=values.night_survival_confidence,
    ),
    # --- Clipping ---
    GivEnergyManagerSensorDescription(
        key="is_clipping",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="is_clipping",
        value_fn=lambda d: "clipping" if d.is_clipping else "normal",
    ),
)
