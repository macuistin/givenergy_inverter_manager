"""HTML report sensors and the pre-boost export recommendation."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy

from .. import sensor_values as values
from ..core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
    build_today_summary_html,
    build_today_summary_state,
    build_week_summary_html,
    build_week_summary_state,
)
from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # ── HTML report sensors (disabled by default) ─────────────────────────────
    GivEnergyManagerSensorDescription(
        key="today_summary",
        translation_key="today_summary",
        icon="mdi:newspaper-variant-outline",
        entity_registry_enabled_default=False,
        value_fn=build_today_summary_state,
        html_fn=build_today_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="charge_plan",
        translation_key="charge_plan",
        icon="mdi:battery-clock-outline",
        entity_registry_enabled_default=False,
        value_fn=build_charge_plan_state,
        html_fn=build_charge_plan_html,
    ),
    GivEnergyManagerSensorDescription(
        key="week_summary",
        translation_key="week_summary",
        icon="mdi:calendar-week-outline",
        entity_registry_enabled_default=False,
        value_fn=build_week_summary_state,
        html_fn=build_week_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_recommended",
        translation_key="pre_boost_export_recommended",
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=False,
        value_fn=lambda d: values.YES if d.pre_boost_export_recommended else values.NO,
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_kwh",
        translation_key="pre_boost_export_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:battery-arrow-up",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_net_gain",
        translation_key="pre_boost_export_net_gain",
        native_unit_of_measurement=CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-plus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_net_gain, 4),
    ),
)
