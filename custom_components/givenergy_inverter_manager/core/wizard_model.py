"""
wizard_model.py - the page table and the plain values the wizard pages work on.

The setup wizard and the options wizard show the same pages. Each page owns a few of the flat
config keys (PAGE_KEYS), and nothing else: a page that was not ticked is never rewritten. The
page logic (validate, clean, summary) lives in wizard_tariff.py and wizard_pages.py and works on
the values in this module, so it needs no Home Assistant.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..const import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_ALT_HEAT_ENABLED,
    CONF_ALT_HEAT_LABEL,
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_BILL_START_DAY,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_IMMERSION_MAX_RUN_MINUTES,
    CONF_IMMERSION_READY_TIMES,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_ALT_HEAT_UNIT,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_COST,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_THROUGHPUT_BUDGET,
    DEFAULT_BILL_START_DAY,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_CURRENCY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_IMMERSION_MAX_RUN_MINUTES,
    DEFAULT_IMMERSION_WATTAGE,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DEFAULT_PSO_LEVY,
    DEFAULT_RATE_PERIODS,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_VAT_RATE,
)
from ..discovery import EVCharger, ForecastSensors
from .inverter_values import RateDefaults

if TYPE_CHECKING:
    from ..inverter.givtcp.discovery import GivTCPInverter

# What the setup wizard offers to set up, and what the options wizard offers to change, in the
# fixed order the pages are shown whatever order the client sends the ticks in. The inverter is
# the only mandatory part of setup, so it has no tick. The EV charger has no setup page: it is
# found by itself.
SETUP_PAGES: tuple[str, ...] = ("tariff", "forecast", "hot_water")
OPTION_PAGES: tuple[str, ...] = ("tariff", "battery", "charge_planning", "hot_water", "ev")

# Each page and the flat config keys it owns. The rate count of the tariff page is derived from
# rate_periods and never stored.
PAGE_KEYS: dict[str, tuple[str, ...]] = {
    "tariff": (CONF_BASE_RATE, CONF_EXPORT_RATE),
    "tariff_rates": (CONF_RATE_PERIODS,),
    "bill": (
        CONF_CURRENCY,
        CONF_BASE_RATE_NAME,
        CONF_BILL_START_DAY,
        CONF_STANDING_CHARGE,
        CONF_PSO_LEVY,
        CONF_VAT_RATE,
        CONF_DISCOUNT_RATE,
    ),
    "schedule_change": (CONF_TARIFF_CHANGES,),
    "battery": (
        CONF_BATTERY_CAPACITY,
        CONF_INVERTER_MAX_OUTPUT,
        CONF_BATTERY_COST,
        CONF_BATTERY_THROUGHPUT_BUDGET,
    ),
    "charge_planning": (
        CONF_BATTERY_MIN_SOC,
        CONF_OVERNIGHT_CHARGE_TARGET,
        CONF_CHARGE_WINTER_MONTHS,
        CONF_CHARGE_SHOULDER_MONTHS,
        CONF_CHARGE_WINTER_USES_FORECAST,
    ),
    "forecast": (
        CONF_FORECAST_ENTITY,
        CONF_FORECAST_ENTITY_P10,
        CONF_FORECAST_ENTITY_D2,
        CONF_CARBON_INTENSITY_ENTITY,
    ),
    "hot_water": (
        CONF_IMMERSION_SWITCH,
        CONF_IMMERSION_TEMP_SENSOR,
        CONF_IMMERSION_WATTAGE,
        CONF_IMMERSION_MAX_RUN_MINUTES,
        CONF_IMMERSION_READY_TIMES,
        CONF_ALT_HEAT_ENABLED,
        CONF_ALT_HEAT_LABEL,
        CONF_ALT_HEAT_COST_UNIT,
        CONF_ALT_HEAT_COST,
        CONF_ALT_HEAT_COST_ENTITY,
    ),
    "ev": (CONF_CAR_EFFICIENCY_KWH_PER_100KM,),
}

# The steps each checklist page runs through. The tariff has up to four. Charge planning has two:
# the planning settings, then the solar forecast sensors, because the forecast shapes the plan.
PAGE_STEPS: dict[str, tuple[str, ...]] = {
    "tariff": ("tariff", "tariff_rates", "bill", "schedule_change"),
    "charge_planning": ("charge_planning", "forecast"),
}

# The keys a checklist page may write, the review date and the dated changes included.
PAGE_WRITES: dict[str, frozenset[str]] = {
    page: frozenset(key for step in PAGE_STEPS.get(page, (page,)) for key in PAGE_KEYS[step])
    | (frozenset({CONF_TARIFF_REVIEWED_ON}) if page == "tariff" else frozenset())
    for page in OPTION_PAGES
}

# What the engine and the coordinator use while a key is unset. A submitted value equal to this
# is not a change, so ticking a page never writes the defaults into the options.
KEY_DEFAULTS: dict[str, Any] = {
    CONF_BASE_RATE: DEFAULT_BASE_RATE,
    CONF_BASE_RATE_NAME: DEFAULT_BASE_RATE_NAME,
    CONF_EXPORT_RATE: DEFAULT_EXPORT_RATE,
    CONF_RATE_PERIODS: DEFAULT_RATE_PERIODS,
    CONF_STANDING_CHARGE: DEFAULT_STANDING_CHARGE,
    CONF_PSO_LEVY: DEFAULT_PSO_LEVY,
    CONF_VAT_RATE: DEFAULT_VAT_RATE,
    CONF_DISCOUNT_RATE: DEFAULT_DISCOUNT_RATE,
    CONF_BILL_START_DAY: DEFAULT_BILL_START_DAY,
    CONF_CURRENCY: DEFAULT_CURRENCY,
    CONF_BATTERY_CAPACITY: DEFAULT_BATTERY_CAPACITY,
    CONF_INVERTER_MAX_OUTPUT: DEFAULT_INVERTER_MAX_OUTPUT,
    CONF_BATTERY_MIN_SOC: DEFAULT_BATTERY_MIN_SOC,
    CONF_OVERNIGHT_CHARGE_TARGET: DEFAULT_OVERNIGHT_CHARGE_TARGET,
    CONF_BATTERY_COST: DEFAULT_BATTERY_COST,
    CONF_BATTERY_THROUGHPUT_BUDGET: DEFAULT_BATTERY_THROUGHPUT_BUDGET,
    CONF_IMMERSION_WATTAGE: DEFAULT_IMMERSION_WATTAGE,
    CONF_IMMERSION_MAX_RUN_MINUTES: DEFAULT_IMMERSION_MAX_RUN_MINUTES,
    CONF_ALT_HEAT_ENABLED: False,
    CONF_CHARGE_WINTER_USES_FORECAST: False,
    CONF_ALT_HEAT_LABEL: DEFAULT_ALT_HEAT_LABEL,
    CONF_ALT_HEAT_COST_UNIT: DEFAULT_ALT_HEAT_UNIT,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM: DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
}


# Every form error a wizard page can return. The form shows the text under this key in
# strings.json (config.error or options.error), so each one needs a line there.
ERROR_KEYS: tuple[str, ...] = (
    "base_rate_required",
    "base_rate_name_missing",
    "rate_period_zero_length",
    "rate_period_duplicate_name",
    "rate_period_name_missing",
    "too_many_periods",
    "tariff_change_date_in_past",
    "immersion_ready_time_invalid",
    "alt_heat_label_empty",
    "alt_heat_label_too_long",
    "missing_entities",
)


class Mode(StrEnum):
    """Which wizard a page is shown in."""

    SETUP = "setup"
    OPTIONS = "options"


@dataclass(frozen=True)
class Detected:
    """What the system already has. It is used and announced, never asked for again."""

    inverters: tuple[GivTCPInverter, ...] = ()
    ev_chargers: tuple[EVCharger, ...] = ()
    forecast: ForecastSensors | None = None
    immersion_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageContext:
    """Everything a page needs besides what the user submitted.

    current   the config in force (saved options over setup data, dated rates applied). Empty
              during setup.
    pending   the values entered on earlier pages of the same run.
    states    entity id to state object, for the read-only checks of a sensor.
    """

    mode: Mode
    today: date
    detected: Detected = field(default_factory=Detected)
    current: Mapping[str, Any] = field(default_factory=dict)
    pending: Mapping[str, Any] = field(default_factory=dict)
    states: Mapping[str, Any] = field(default_factory=dict)
    home_currency: str = DEFAULT_CURRENCY
    rate_defaults: RateDefaults | None = None  # what the inverter integration holds, setup only
    latitude: float = 0.0  # Home Assistant's, for the default seasons

    def value(self, key: str, default: Any = None) -> Any:
        """The value of *key*: entered earlier in this run, else in force, else *default*."""
        if key in self.pending:
            return self.pending[key]
        return self.current.get(key, default)


@dataclass(frozen=True)
class Validation:
    """What is wrong with a submission (errors stop it) and what to check (warnings do not)."""

    errors: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def is_unset(value: Any) -> bool:
    """None, an empty string and an empty list all mean nothing is set.

    None and the empty string are unset in core/reload_policy.py too. An empty list is what a
    cleared list of ready times looks like.
    """
    return value is None or value == "" or value == []


def same_value(left: Any, right: Any) -> bool:
    """True when two config values are the same setting."""
    if is_unset(left) and is_unset(right):
        return True
    return left == right


def changed_values(
    values: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """The part of *values* that differs from the config in force.

    A key unset in *current* counts as the value the engine uses then (KEY_DEFAULTS).
    """
    return {
        key: value
        for key, value in values.items()
        if not same_value(value, current.get(key, KEY_DEFAULTS.get(key)))
    }
