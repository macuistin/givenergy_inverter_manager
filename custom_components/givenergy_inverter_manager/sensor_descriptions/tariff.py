"""Current tariff sensors: the live rate, the next cheap period and rate savings."""

from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass

from .. import sensor_values as values
from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Current tariff ---
    GivEnergyManagerSensorDescription(
        key="current_rate",
        translation_key="current_rate",
        native_unit_of_measurement=CURRENCY_UNIT,  # unit resolved dynamically
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.current_rate, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="current_rate_period",
        translation_key="current_rate_period",
        value_fn=lambda d: d.current_rate_name,
    ),
    GivEnergyManagerSensorDescription(
        key="live_grid_cost_rate",
        translation_key="live_grid_cost_rate",
        native_unit_of_measurement=CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.live_grid_cost_rate,
    ),
    GivEnergyManagerSensorDescription(
        key="next_cheap_rate_start",
        translation_key="next_cheap_rate_start",
        icon="mdi:clock-time-four-outline",
        entity_registry_enabled_default=False,
        value_fn=values.next_cheap_rate_start,
        attrs_fn=values.cheap_rate_attributes,
    ),
    GivEnergyManagerSensorDescription(
        key="hours_to_cheap_rate",
        translation_key="hours_to_cheap_rate",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-countdown-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.hours_to_cheap_rate,
    ),
    GivEnergyManagerSensorDescription(
        key="cheapest_rate",
        translation_key="cheapest_rate",
        native_unit_of_measurement=CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.cheapest_rate, 4) if d.cheapest_rate_name else None,
    ),
    GivEnergyManagerSensorDescription(
        key="cheapest_rate_period",
        translation_key="cheapest_rate_period",
        icon="mdi:clock-time-four-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.cheapest_rate_name if d.cheapest_rate_name else None,
    ),
    GivEnergyManagerSensorDescription(
        key="is_on_cheapest_rate",
        translation_key="is_on_cheapest_rate",
        icon="mdi:cash-check",
        entity_registry_enabled_default=False,
        value_fn=lambda d: values.YES if d.is_on_cheapest_rate else values.NO,
    ),
    GivEnergyManagerSensorDescription(
        key="is_on_base_rate",
        translation_key="is_on_base_rate",
        icon="mdi:cash",
        entity_registry_enabled_default=False,
        value_fn=lambda d: values.YES if d.is_on_base_rate else values.NO,
    ),
    GivEnergyManagerSensorDescription(
        key="minutes_remaining_in_period",
        translation_key="minutes_remaining_in_period",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-end",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.minutes_remaining_in_period,
    ),
    GivEnergyManagerSensorDescription(
        key="rate_savings_vs_daytime",
        translation_key="rate_savings_vs_daytime",
        native_unit_of_measurement=CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-fast",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.rate_savings_vs_daytime, 4),
    ),
)
