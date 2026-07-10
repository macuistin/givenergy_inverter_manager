# ruff: noqa: E402
"""
conftest.py — Pytest configuration for GivEnergy Inverter Manager.

Pure logic modules (tariff, optimizer, battery, discovery) have zero
HA dependencies and are tested in isolation. The __init__.py of the package
imports HA, so we stub the entire homeassistant namespace before any test
module is collected, preventing ImportError without a real HA install.

We also stub voluptuous (used by config_flow) and make DataUpdateCoordinator
a proper Generic so coordinator.py's type annotation compiles cleanly.
"""

import os
import sys
import types
from typing import Generic, TypeVar
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Build homeassistant stub modules
# ---------------------------------------------------------------------------
_HA_SUBMODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.const",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.config_validation",
    "homeassistant.components",
    "homeassistant.components.repairs",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.number",
    "homeassistant.util",
    "homeassistant.util.dt",
    "voluptuous",
]
for _mod_name in _HA_SUBMODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

# --- homeassistant.util.dt ---
_dt_util = sys.modules["homeassistant.util.dt"]
_dt_util.as_local = lambda dt: dt
sys.modules["homeassistant.util"].dt = _dt_util

# --- homeassistant.const ---
_const = sys.modules["homeassistant.const"]
_const.Platform = MagicMock()
_const.PERCENTAGE = "%"
_const.UnitOfPower = MagicMock()
_const.UnitOfEnergy = MagicMock()
_const.UnitOfTemperature = MagicMock()
_const.EntityCategory = MagicMock()

# --- homeassistant.config_entries ---
_ce = sys.modules["homeassistant.config_entries"]
_ce.ConfigEntry = MagicMock


class _ConfigFlow:
    """Stub that accepts domain= keyword in subclass definition."""

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)


class _OptionsFlow:
    pass


_ce.ConfigFlow = _ConfigFlow
_ce.OptionsFlow = _OptionsFlow
_ce.callback = lambda f: f

# --- homeassistant.core ---
_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = MagicMock
_core.callback = lambda f: f

# --- homeassistant.exceptions ---
_exc = sys.modules["homeassistant.exceptions"]
_exc.ConfigEntryNotReady = Exception
_exc.HomeAssistantError = Exception


class _ServiceValidationError(Exception):
    """Stub that mirrors HA's ServiceValidationError signature."""

    def __init__(self, *args, translation_domain=None, translation_key=None, **kwargs):
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key


_exc.ServiceValidationError = _ServiceValidationError

# --- DataUpdateCoordinator: must be Generic so coordinator.py's
#     DataUpdateCoordinator[CoordinatorData] annotation works ---
_T = TypeVar("_T")


class _DataUpdateCoordinator(Generic[_T]):
    """Minimal stub that supports generic subscript syntax."""

    def __init__(self, *args, **kwargs):
        pass


class _CoordinatorEntity(Generic[_T]):
    """Minimal stub for CoordinatorEntity."""

    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator

    def async_write_ha_state(self):
        pass


_coord = sys.modules["homeassistant.helpers.update_coordinator"]
_coord.DataUpdateCoordinator = _DataUpdateCoordinator
_coord.CoordinatorEntity = _CoordinatorEntity


class _UpdateFailed(Exception):
    """Stub that mirrors HA's UpdateFailed signature (accepts translation kwargs)."""

    def __init__(self, *args, translation_domain=None, translation_key=None, **kwargs):
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key


_coord.UpdateFailed = _UpdateFailed

# --- repairs ---
_repairs = sys.modules["homeassistant.components.repairs"]
_repairs.async_create_issue = MagicMock()
_repairs.async_delete_issue = MagicMock()
_repairs.IssueSeverity = MagicMock()
_repairs.IssueSeverity.WARNING = "warning"

# --- repairs ---
_repairs = sys.modules["homeassistant.components.repairs"]
_repairs.async_create_issue = MagicMock()
_repairs.async_delete_issue = MagicMock()
_repairs.IssueSeverity = MagicMock()
_repairs.IssueSeverity.WARNING = "warning"

# --- sensor ---
_sensor = sys.modules["homeassistant.components.sensor"]
_sensor.SensorEntity = object
_sensor.SensorEntityDescription = object
_sensor.SensorDeviceClass = MagicMock()
_sensor.SensorStateClass = MagicMock()

# --- switch ---
_switch = sys.modules["homeassistant.components.switch"]
_switch.SwitchEntity = object
_switch.SwitchEntityDescription = object

# --- number ---
_number = sys.modules["homeassistant.components.number"]
_number.NumberEntity = object
_number.NumberMode = MagicMock()
_number.RestoreNumber = type("RestoreNumber", (), {})

# --- helpers ---
_sel = sys.modules["homeassistant.helpers.selector"]
for _cls in [
    "EntitySelector",
    "EntitySelectorConfig",
    "NumberSelector",
    "NumberSelectorConfig",
    "SelectSelector",
    "SelectSelectorConfig",
    "SelectOptionDict",
    "TextSelector",
    "TextSelectorConfig",
]:
    setattr(_sel, _cls, MagicMock)

_cv = sys.modules["homeassistant.helpers.config_validation"]
_cv.string = str

_ep = sys.modules["homeassistant.helpers.entity_platform"]
_ep.AddEntitiesCallback = MagicMock

# homeassistant.helpers.event (used by coordinator for time tracking)
if "homeassistant.helpers.event" not in sys.modules:
    sys.modules["homeassistant.helpers.event"] = types.ModuleType("homeassistant.helpers.event")
sys.modules["homeassistant.helpers.event"].async_track_time_change = lambda *a, **kw: lambda: None


# homeassistant.core needs ServiceCall for dashboard.py
_core = sys.modules["homeassistant.core"]
_core.ServiceCall = MagicMock

# homeassistant.helpers.entity_registry (used by dashboard.py)
if "homeassistant.helpers.entity_registry" not in sys.modules:
    sys.modules["homeassistant.helpers.entity_registry"] = types.ModuleType(
        "homeassistant.helpers.entity_registry"
    )
sys.modules["homeassistant.helpers.entity_registry"].async_get = MagicMock(return_value=MagicMock())

# --- voluptuous ---
_vol = sys.modules["voluptuous"]
_vol.Schema = MagicMock
_vol.Required = MagicMock
_vol.Optional = MagicMock

# ---------------------------------------------------------------------------
# Add repo root to path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Shared test helpers (used by test_tariff.py, test_engine.py, test_scenarios.py)
# ---------------------------------------------------------------------------
from datetime import datetime

from custom_components.givenergy_inverter_manager.const import DEFAULT_RATE_PERIODS
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    RawSensorValues,
    build_coordinator_data,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator


def _nightboost_cfg() -> dict:
    """Config dict matching Electric Ireland Home Electric + Nightboost."""
    return {
        "base_rate": 0.3334,
        "base_rate_name": "Day",
        "rate_periods": DEFAULT_RATE_PERIODS,
        "export_rate": 0.195,
        "standing_charge_per_day": 0.8259,
        "pso_levy_per_month": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 16,
        "currency": "EUR",
        "battery_min_soc_pct": 10,
        "skip_charge_soc_threshold_pct": 75,
        "immersion_target_temp_c": 55,
        "immersion_min_temp_c": 45,
        "ev_battery_protect_soc_pct": 20,
        "battery_capacity_kwh": 19.0,
        "inverter_max_output_kw": 5.0,
    }


def _raw(**overrides) -> RawSensorValues:
    base = RawSensorValues(
        solar_power_w=2000.0,
        battery_soc=60.0,
        battery_power_w=-500.0,
        grid_power_w=0.0,
        house_load_w=1500.0,
        inverter_max_w=5000.0,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _run(
    raw=None,
    cfg=None,
    now=None,
    acc=None,
    last_soc=None,
    last_update_time=None,
    battery_stats=None,
    **kwargs,
):
    """Run one engine cycle and return (CoordinatorData, ev_target_mode)."""
    if raw is None:
        raw = _raw()
    if cfg is None:
        cfg = _nightboost_cfg()
    if now is None:
        now = datetime(2024, 6, 15, 14, 0)
    if acc is None:
        acc = EnergyAccumulator()
    if battery_stats is None:
        battery_stats = BatteryStats()
    return build_coordinator_data(
        raw=raw,
        cfg=cfg,
        acc=acc,
        battery_stats=battery_stats,
        last_soc=last_soc,
        last_update_time=last_update_time,
        now=now,
        ev_charger=kwargs.get("ev_charger"),
        override_charge_target=kwargs.get("override_charge_target"),
        override_immersion=kwargs.get("override_immersion"),
        override_skip_charge=kwargs.get("override_skip_charge", False),
    )
