"""
wizard_changes.py - what the confirm step of a wizard tells the user.

The options wizard confirm step lists every changed value as before and after, in plain words,
then one line: whether the change applies now or reloads the integration, and what makes it
reload. The setup wizard confirm step lists what was found and what was entered.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
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
)
from .reload_policy import Effect, change_effect, changed_keys, reload_keys
from .wizard_model import KEY_DEFAULTS, is_unset
from .wizard_tariff import periods_text

LABELS: dict[str, str] = {
    CONF_BASE_RATE: "Base rate",
    CONF_EXPORT_RATE: "Export rate",
    CONF_RATE_PERIODS: "Time-of-day rates",
    CONF_BASE_RATE_NAME: "Base rate name",
    CONF_CURRENCY: "Currency",
    CONF_BILL_START_DAY: "Bill start day",
    CONF_STANDING_CHARGE: "Standing charge per day",
    CONF_PSO_LEVY: "Fixed levy per billing period",
    CONF_VAT_RATE: "VAT",
    CONF_DISCOUNT_RATE: "Supplier discount",
    CONF_TARIFF_CHANGES: "Scheduled rate changes (start dates)",
    CONF_TARIFF_REVIEWED_ON: "Tariff last confirmed",
    CONF_BATTERY_CAPACITY: "Battery capacity",
    CONF_INVERTER_MAX_OUTPUT: "Inverter maximum output",
    CONF_BATTERY_MIN_SOC: "Battery minimum charge",
    CONF_OVERNIGHT_CHARGE_TARGET: "Overnight charge cap",
    CONF_BATTERY_COST: "Battery cost",
    CONF_BATTERY_THROUGHPUT_BUDGET: "Daily throughput budget",
    CONF_FORECAST_ENTITY: "Forecast sensor",
    CONF_FORECAST_ENTITY_P10: "Pessimistic forecast sensor",
    CONF_FORECAST_ENTITY_D2: "Day after tomorrow forecast sensor",
    CONF_CARBON_INTENSITY_ENTITY: "Carbon intensity sensor",
    CONF_IMMERSION_SWITCH: "Immersion switch",
    CONF_IMMERSION_TEMP_SENSOR: "Hot water temperature sensor",
    CONF_IMMERSION_WATTAGE: "Immersion element power",
    CONF_IMMERSION_READY_TIMES: "Hot water ready times",
    CONF_ALT_HEAT_ENABLED: "Alternative water heating",
    CONF_ALT_HEAT_LABEL: "Alternative heating name",
    CONF_ALT_HEAT_COST_UNIT: "Alternative heating cost is",
    CONF_ALT_HEAT_COST: "Alternative heating cost",
    CONF_ALT_HEAT_COST_ENTITY: "Alternative heating cost sensor",
    CONF_CAR_EFFICIENCY_KWH_PER_100KM: "Car efficiency",
}

# What a value is quoted in, appended to a number.
_UNITS: dict[str, str] = {
    CONF_BATTERY_CAPACITY: " kWh",
    CONF_INVERTER_MAX_OUTPUT: " kW",
    CONF_BATTERY_MIN_SOC: "%",
    CONF_OVERNIGHT_CHARGE_TARGET: "%",
    CONF_BATTERY_THROUGHPUT_BUDGET: " kWh",
    CONF_IMMERSION_WATTAGE: " W",
    CONF_CAR_EFFICIENCY_KWH_PER_100KM: " kWh per 100 km",
    CONF_VAT_RATE: "%",
    CONF_DISCOUNT_RATE: "%",
}

_NOT_SET = "not set"


def _periods(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return periods_text(value)


def _changes(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(str(item.get("effective")) for item in value if isinstance(item, dict))


def show(key: str, value: Any) -> str:
    """One config value in words."""
    if key == CONF_RATE_PERIODS:
        return _periods(value)
    if key == CONF_TARIFF_CHANGES:
        return _changes(value)
    if is_unset(value) or value == []:
        return _NOT_SET
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}{_UNITS.get(key, '')}"
    return f"{value}{_UNITS.get(key, '')}"


def _value_of(config: Mapping[str, Any], key: str) -> Any:
    return config.get(key, KEY_DEFAULTS.get(key))


def describe_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """One line for each changed key, in plain words: "Base rate: 0.3 to 0.32"."""
    return [
        f"{LABELS.get(key, key)}: {show(key, _value_of(before, key))} "
        f"to {show(key, _value_of(after, key))}"
        for key in sorted(changed_keys(before, after), key=lambda k: LABELS.get(k, k))
    ]


def effect_line(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Whether the change applies now, and what makes the integration reload when it does."""
    effect = change_effect(before, after)
    if effect is Effect.NONE:
        return "Nothing changes."
    if effect is Effect.LIVE:
        return "Applies now. The integration does not reload."
    names = sorted(LABELS.get(key, key).lower() for key in reload_keys(before, after))
    return (
        f"Reloads the integration because you changed {', '.join(names)}. "
        "Its entities are unavailable for a few seconds."
    )


def confirm_text(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """The options confirm step: every change, then the effect."""
    lines = describe_changes(before, after)
    body = "\n".join(f"- {line}" for line in lines) if lines else "No values changed."
    return f"{body}\n\n{effect_line(before, after)}"
