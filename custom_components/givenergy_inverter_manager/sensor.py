"""
sensor.py — Sensor platform for GivEnergy Inverter Manager.

Exposes all calculated and tracked values as Home Assistant sensor entities.
A sensor that needs an optional device (an EV charger, the immersion switch or its
temperature sensor) is created only while that device is present. See optional_devices.py.

Every sensor reads from the shared GivEnergyCoordinator data snapshot —
no direct polling of GivTCP or any external source.

The description table lives in the sensor_descriptions package, one module per theme
(power, tariff, today, bill, battery, decisions, loads, diagnostics, forecast, week,
month and year, reports, and so on). The value rules live in sensor_values.py. This
module holds the entity class and the platform setup.

All sensors use the CoordinatorEntity mixin so they update automatically
whenever the coordinator refreshes, and become unavailable if the coordinator
fails (e.g. GivTCP goes offline).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_FULL_TEXT, DEFAULT_CURRENCY_SYMBOL
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.devices import Device
from .core.text_state import fit_state
from .entity import GivEnergyEntity
from .optional_devices import async_add_entities_per_device
from .sensor_descriptions import SENSOR_DESCRIPTIONS
from .sensor_descriptions.base import (
    CURRENCY_UNIT,
    GivEnergyManagerSensorDescription,
    reset_period_of,
)

_RESET_FIELDS = {
    "day": "last_reset_time",
    "week": "week_start_time",
    "month": "month_start_time",
    "year": "year_start_time",
}

_LOG = logging.getLogger(__name__)

# Attributes that stay visible live but are not written to the recorder. Home Assistant stores a
# new set of attributes whenever one changes, even when the state did not, and sends a
# state_changed event. These change often or are long, so they would write a row each time. The
# list is one class attribute, so a name has to be unique across the sensors.
_UNRECORDED_ATTRIBUTES = frozenset(
    {
        "html",
        ATTR_FULL_TEXT,
        # Charge register writes and outside changes, newest first.
        "recent_writes",
        # Night survival: the live numbers behind the level.
        "battery_soc",
        "estimated_soc_at_sunrise",
        "minimum_soc",
        "warning_below_soc",
        # Self-sufficiency: where the period's energy came from.
        "house_load_kwh",
        "from_grid_kwh",
        "grid_to_battery_kwh",
        "from_solar_and_battery_kwh",
        # The water temperature: the ready-by plan.
        "ready_by",
        "expected_ready",
        "heating_rate_c_per_h",
        "heating_rate_source",
        "planned_heating",
        # Alternative heating: the costs behind the advice, its timings and the learned schedule.
        "alt_cost_per_kwh",
        "electricity_cost_per_kwh",
        "cheapest_electricity_cost_per_kwh",
        "alt_saving_per_kwh",
        "best_hours_for_alt",
        "horizon_ends",
        "alt_start_by",
        "alt_run_minutes",
        "alt_for_ready_time",
        "alt_keep_warm",
        "alt_schedule",
        "alt_schedule_saving",
        "alt_schedule_days",
        "alt_schedule_suggestion",
    }
)


# Coordinator-driven — no parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        GivEnergyManagerSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if description.requires is None
    )

    def _sensors_of(device: Device) -> list[GivEnergyManagerSensor]:
        return [
            GivEnergyManagerSensor(coordinator, description)
            for description in SENSOR_DESCRIPTIONS
            if description.requires == device
        ]

    async_add_entities_per_device(entry, async_add_entities, _sensors_of)


class GivEnergyManagerSensor(GivEnergyEntity, SensorEntity):
    """A sensor entity for GivEnergy Inverter Manager."""

    entity_description: GivEnergyManagerSensorDescription
    _unrecorded_attributes = _UNRECORDED_ATTRIBUTES

    def __init__(
        self,
        coordinator: GivEnergyCoordinator,
        description: GivEnergyManagerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._reset_period = reset_period_of(description)
        self._value_error_logged = False

    @property
    def native_unit_of_measurement(self) -> str | None:
        """
        Return the unit of measurement.

        For monetary sensors the unit is the configured currency symbol,
        read from coordinator data so it updates when the user changes
        their currency in the options flow without restarting HA.
        """
        declared = self.entity_description.native_unit_of_measurement
        if declared == CURRENCY_UNIT:
            if self.coordinator.data is not None:
                return self.coordinator.data.currency_symbol
            return DEFAULT_CURRENCY_SYMBOL  # safe fallback before first update
        return declared

    @property
    def last_reset(self) -> datetime | None:
        """Return when the sensor's accumulation period started (enables HA long-term stats)."""
        if self._reset_period is None:
            return None
        if self.entity_description.state_class != SensorStateClass.TOTAL:
            return None
        data = self.coordinator.data
        if not data:
            return None
        iso = getattr(data, _RESET_FIELDS[self._reset_period], "")
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso)
            # Stored as local timezone since coordinator fix; old UTC values
            # have no tzinfo so fall back to UTC for backwards compatibility.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the html attribute of report sensors and any attributes that explain the state."""
        description = self.entity_description
        data = self.coordinator.data
        if data is None:
            return None
        attrs: dict = {}
        if description.html_fn is not None:
            attrs["html"] = description.html_fn(data)
        if description.attrs_fn is not None:
            attrs.update(description.attrs_fn(data) or {})
        attrs.update(self._full_text_attributes())
        return attrs or None

    def _full_text_attributes(self) -> dict[str, str]:
        """The full text of a sentence sensor, only when its state had to be cut."""
        value = self._value()
        if not isinstance(value, str):
            return {}
        fitted = fit_state(value)
        return {ATTR_FULL_TEXT: fitted.full} if fitted.was_cut else {}

    @property
    def native_value(self) -> Any:
        """Return the sensor value, a sentence cut to fit Home Assistant's state length."""
        value = self._value()
        return fit_state(value).state if isinstance(value, str) else value

    def _value(self) -> Any:
        """Return the value_fn result from coordinator data, None before data or on a failure."""
        if self.coordinator.data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except Exception as exc:  # noqa: BLE001
            self._warn_once_value_fn_raised(exc)
            return None

    def _warn_once_value_fn_raised(self, exc: Exception) -> None:
        """Log the first value_fn failure of this sensor, then stay quiet."""
        if not self._value_error_logged:
            self._value_error_logged = True
            _LOG.warning("Sensor %s value_fn raised: %s", self.entity_description.key, exc)

    @property
    def available(self) -> bool:
        """Return True if coordinator has data and the entity is applicable."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return False
        return self.entity_description.available_fn(self.coordinator.data)
