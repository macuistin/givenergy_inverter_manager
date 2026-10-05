"""Bill prediction sensors for the current bill period."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Bill prediction ---
    GivEnergyManagerSensorDescription(
        key="accrued_bill",
        translation_key="accrued_bill",
        native_unit_of_measurement=CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        value_fn=lambda d: round(d.accrued_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="projected_bill",
        translation_key="projected_bill",
        native_unit_of_measurement=CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        value_fn=lambda d: round(d.projected_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="days_remaining_in_period",
        translation_key="days_remaining_in_period",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.days_remaining,
    ),
)
