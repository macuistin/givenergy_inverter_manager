"""
selectors.py - the number bounds and the selectors every wizard form uses.

One table of bounds is shared by the setup wizard, the options wizard and the repair that asks
for the battery cost, so a bound changes in one place. The tuning controls (controls.py) keep
their own ranges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.helpers import selector

from ..const import (
    ALT_HEAT_UNIT_KWH_HEAT,
    ALT_HEAT_UNIT_LITRE,
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_BASE_RATE,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_BILL_START_DAY,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_IMMERSION_MAX_RUN_MINUTES,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_PSO_LEVY,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
    CURRENCIES,
    DEFAULT_CURRENCY,
)
from ..core.wizard_tariff import MAX_RATE_PERIODS


@dataclass(frozen=True)
class Bounds:
    """Range, step and unit of one number field."""

    low: float
    high: float
    step: float
    unit: str | None = None
    mode: str | None = None


# A price, a cost or a size is typed in a box. A slider over thousands of steps, as a price to
# 0.001 or a battery cost to 100 is, cannot be set to a figure read off a bill. A percentage,
# a day of the month and a short range stay sliders.
BOX = "box"

NUMBER_BOUNDS: dict[str, Bounds] = {
    CONF_BASE_RATE: Bounds(0, 5, 0.001, mode=BOX),
    CONF_EXPORT_RATE: Bounds(0, 1, 0.001, mode=BOX),
    CONF_STANDING_CHARGE: Bounds(0, 5, 0.001, mode=BOX),
    CONF_PSO_LEVY: Bounds(0, 20, 0.01, mode=BOX),
    CONF_VAT_RATE: Bounds(0, 30, 0.1, "%"),
    CONF_DISCOUNT_RATE: Bounds(0, 20, 0.1, "%"),
    CONF_BILL_START_DAY: Bounds(1, 28, 1),
    CONF_BATTERY_MIN_SOC: Bounds(5, 30, 1, "%"),
    CONF_OVERNIGHT_CHARGE_TARGET: Bounds(20, 100, 1, "%"),
    CONF_BATTERY_COST: Bounds(0, 20000, 100, mode=BOX),
    CONF_BATTERY_THROUGHPUT_BUDGET: Bounds(0, 50, 0.5, "kWh", BOX),
    CONF_BATTERY_CAPACITY: Bounds(1, 100, 0.1, "kWh", BOX),
    CONF_INVERTER_MAX_OUTPUT: Bounds(1, 20, 0.1, "kW", BOX),
    CONF_IMMERSION_WATTAGE: Bounds(500, 6000, 100, "W", BOX),
    # 0 turns the limit off, so the box has to allow it.
    CONF_IMMERSION_MAX_RUN_MINUTES: Bounds(0, 240, 5, "min", BOX),
    CONF_CAR_EFFICIENCY_KWH_PER_100KM: Bounds(5, 40, 0.1, "kWh/100km", BOX),
    # A box, not a slider: a slider cannot be left empty, and empty means no advice.
    CONF_ALT_HEAT_COST: Bounds(0.001, 5, 0.001, mode=BOX),
}

# What each price field is quoted per. The currency code comes from the form.
PRICE_PER: dict[str, str] = {
    CONF_BASE_RATE: "kWh",
    CONF_EXPORT_RATE: "kWh",
    CONF_STANDING_CHARGE: "day",
    CONF_PSO_LEVY: "month",
}

RATE_COUNT_KEY = "rate_count"
PAGES_KEY = "pages"


def currency_code(code: object) -> str:
    """Return *code* when it is an offered currency, else the default currency."""
    return code if isinstance(code, str) and code in CURRENCIES else DEFAULT_CURRENCY


def money_unit(code: object, per: str) -> str:
    """Unit text for a price field, such as GBP/kWh."""
    return f"{currency_code(code)}/{per}"


def number_selector(key: str, unit: str | None = None) -> selector.NumberSelector:
    """Number selector for *key*, using *unit* in place of the table unit when given."""
    bounds = NUMBER_BOUNDS[key]
    config: dict[str, Any] = {"min": bounds.low, "max": bounds.high, "step": bounds.step}
    if unit or bounds.unit:
        config["unit_of_measurement"] = unit or bounds.unit
    if bounds.mode:
        config["mode"] = bounds.mode
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def price_selector(key: str, currency: object) -> selector.NumberSelector:
    """Number selector for a price field, with the unit following *currency*."""
    return number_selector(key, money_unit(currency, PRICE_PER[key]))


def battery_cost_selector(currency: object) -> selector.NumberSelector:
    """Number selector for the battery cost, in the symbol of *currency*.

    Shared by the battery page and the repair that asks for the cost.
    """
    return number_selector(CONF_BATTERY_COST, CURRENCIES[currency_code(currency)])


def entity_selector(domain: str | list[str] = "sensor") -> selector.EntitySelector:
    """Entity picker limited to *domain*."""
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def alt_heat_unit_selector() -> selector.SelectSelector:
    """Litre or kWh of heat. The option labels are in strings.json under selector."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[ALT_HEAT_UNIT_LITRE, ALT_HEAT_UNIT_KWH_HEAT],
            translation_key=CONF_ALT_HEAT_COST_UNIT,
        )
    )


def currency_selector() -> selector.SelectSelector:
    """The offered currencies, as code and symbol."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=code, label=f"{code} ({symbol})")
                for code, symbol in CURRENCIES.items()
            ]
        )
    )


def rate_count_selector() -> selector.SelectSelector:
    """How many time-of-day rates there are besides the base rate: 0 to the form cap."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[str(n) for n in range(MAX_RATE_PERIODS + 1)],
            translation_key=RATE_COUNT_KEY,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


_MONTHS = (
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


def months_selector() -> selector.SelectSelector:
    """A list of the twelve months, to tick any number of them. The values are 1 to 12."""
    return checklist_selector(
        [selector.SelectOptionDict(value=str(n), label=name) for n, name in enumerate(_MONTHS, 1)]
    )


def checklist_selector(
    options: list[selector.SelectOptionDict] | list[str], translation_key: str | None = None
) -> selector.SelectSelector:
    """A list of checkboxes: a multi-select shown as a list, one box per page."""
    config: dict[str, Any] = {
        "options": options,
        "multiple": True,
        "mode": selector.SelectSelectorMode.LIST,
    }
    if translation_key:
        config["translation_key"] = translation_key
    return selector.SelectSelector(selector.SelectSelectorConfig(**config))
