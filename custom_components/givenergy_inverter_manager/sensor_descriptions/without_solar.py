"""What the electricity would have cost with no solar and no battery."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .base import CURRENCY_UNIT, MONEY_PRECISION, GivEnergyManagerSensorDescription

# The house load priced at the rate in force when it was used, with the supplier discount and VAT,
# as the Import Cost sensors price what was imported. See grid_equivalent_load_cost in
# core/tariff.py.
DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    GivEnergyManagerSensorDescription(
        key="cost_without_solar_today",
        is_daily_total=True,
        translation_key="cost_without_solar_today",
        native_unit_of_measurement=CURRENCY_UNIT,
        suggested_display_precision=MONEY_PRECISION,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power-variant-outline",
        value_fn=lambda d: round(d.today.grid_equivalent_load_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="cost_without_solar_this_week",
        translation_key="cost_without_solar_this_week",
        native_unit_of_measurement=CURRENCY_UNIT,
        suggested_display_precision=MONEY_PRECISION,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:solar-power-variant-outline",
        value_fn=lambda d: round(d.week.grid_equivalent_load_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="cost_without_solar_this_month",
        translation_key="cost_without_solar_this_month",
        native_unit_of_measurement=CURRENCY_UNIT,
        suggested_display_precision=MONEY_PRECISION,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:solar-power-variant-outline",
        value_fn=lambda d: round(d.month.grid_equivalent_load_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="bill_without_solar",
        translation_key="bill_without_solar",
        native_unit_of_measurement=CURRENCY_UNIT,
        suggested_display_precision=MONEY_PRECISION,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:receipt-text-outline",
        value_fn=lambda d: round(d.bill_without_solar, 2),
    ),
)
