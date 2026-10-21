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
    CONF_BATTERY_CAPACITY_ENTITY,
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
    CONF_IMMERSION_RUN_LIMIT_WARNING,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_MAX_OUTPUT_ENTITY,
    CONF_INVERTER_SERIAL,
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
from .wizard_pages import battery_summary, forecast_summary, hot_water_summary
from .wizard_tariff import periods_text, tariff_summary

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
    CONF_BATTERY_CAPACITY_ENTITY: "Battery capacity sensor",
    CONF_INVERTER_MAX_OUTPUT_ENTITY: "Inverter maximum output sensor",
    CONF_INVERTER_MAX_OUTPUT: "Inverter maximum output",
    CONF_BATTERY_MIN_SOC: "Battery minimum charge",
    CONF_OVERNIGHT_CHARGE_TARGET: "Overnight charge cap",
    CONF_BATTERY_COST: "Battery cost",
    CONF_BATTERY_THROUGHPUT_BUDGET: "Daily throughput budget",
    CONF_CHARGE_WINTER_MONTHS: "Winter months",
    CONF_CHARGE_SHOULDER_MONTHS: "Shoulder months",
    CONF_CHARGE_WINTER_USES_FORECAST: "Plan winter charges from the forecast",
    CONF_FORECAST_ENTITY: "Forecast sensor",
    CONF_FORECAST_ENTITY_P10: "Pessimistic forecast sensor",
    CONF_FORECAST_ENTITY_D2: "Day after tomorrow forecast sensor",
    CONF_CARBON_INTENSITY_ENTITY: "Carbon intensity sensor",
    CONF_IMMERSION_SWITCH: "Immersion switch",
    CONF_IMMERSION_TEMP_SENSOR: "Hot water temperature sensor",
    CONF_IMMERSION_WATTAGE: "Immersion element power",
    CONF_IMMERSION_MAX_RUN_MINUTES: "Longest immersion run",
    CONF_IMMERSION_RUN_LIMIT_WARNING: "Warn when the longest run is reached",
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
    CONF_IMMERSION_MAX_RUN_MINUTES: " minutes",
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


_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _month_names(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "none"
    return ", ".join(_MONTH_NAMES[int(m) - 1] for m in sorted(value) if 1 <= int(m) <= 12)


def show(key: str, value: Any) -> str:
    """One config value in words."""
    if key in (CONF_CHARGE_WINTER_MONTHS, CONF_CHARGE_SHOULDER_MONTHS):
        return _month_names(value)
    if key == CONF_RATE_PERIODS:
        return _periods(value)
    if key == CONF_TARIFF_CHANGES:
        return _changes(value)
    if is_unset(value):
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


# ── The setup wizard confirm step ─────────────────────────────────────────────

DRY_RUN_SENTENCE = (
    "Dry run is on. Nothing is sent to your inverter, immersion or EV charger until you "
    "turn off the Dry run switch."
)
NO_TARIFF_SENTENCE = (
    "Tariff: not set yet. Costs and the overnight plan use a placeholder rate until you set "
    "the tariff under Configure."
)


def _tariff_lines(values: Mapping[str, Any]) -> list[str]:
    rows = values.get(CONF_RATE_PERIODS) or []
    base_name = values.get(CONF_BASE_RATE_NAME, KEY_DEFAULTS[CONF_BASE_RATE_NAME])
    return [
        tariff_summary(values),
        f"Base rate: {base_name} {float(values[CONF_BASE_RATE]):.4f}. "
        f"Timed rates: {periods_text(rows) or 'none'}.",
    ]


def _sentence(text: str) -> str:
    """*text* with its first letter in capitals and the rest left as written."""
    return text[:1].upper() + text[1:]


def setup_summary(values: Mapping[str, Any], charger: str | None, *, tariff_asked: bool) -> str:
    """The setup confirm step: what was found, what was entered, and that dry run is on."""
    serial = values.get(CONF_INVERTER_SERIAL)
    lines = [f"Inverter: {serial}."] if serial else []
    lines += _tariff_lines(values) if tariff_asked else [NO_TARIFF_SENTENCE]
    lines += [
        f"{_sentence(battery_summary(values))}.",
        f"EV charger: {charger or 'none found, one is picked up when it appears'}.",
        f"Solar {forecast_summary(values)}.",
        f"Hot water: {hot_water_summary(values)}.",
        DRY_RUN_SENTENCE,
    ]
    return "\n".join(f"- {line}" for line in lines if line)
