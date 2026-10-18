"""
schemas.py - the form of each wizard page, built from the context of the moment.

A schema is built when its form is shown, so the screen after the tariff has exactly as many
rate rows as the count the user chose. The values in force (options wizard) or the defaults for
a new install (setup wizard) become the defaults of the fields. A field the user may leave empty
has no default, so an emptied selector reaches the flow as a missing key.

The setup wizard asks for less than the options wizard. A new install asks for no battery or car
detail, because the defaults are one tick away in the options wizard, and its tariff page has no
defaults, because a placeholder rate is not a real one.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

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
    CONF_VAT_RATE,
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_ALT_HEAT_UNIT,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BILL_START_DAY,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_IMMERSION_MAX_RUN_MINUTES,
    DEFAULT_IMMERSION_WATTAGE,
)
from ..core.seasons import season_defaults
from ..core.tariff import scheduled_tariff_changes
from ..core.wizard_model import KEY_DEFAULTS, Mode, PageContext
from ..core.wizard_tariff import (
    default_rate_rows,
    night_window,
    rate_count,
    rate_prefill,
)
from .selectors import (
    alt_heat_unit_selector,
    battery_cost_selector,
    currency_code,
    currency_selector,
    entity_selector,
    months_selector,
    number_selector,
    price_selector,
    rate_count_selector,
)

ALT_HEAT_SECTION = "alt_heat"
BILL_SECTION = "bill_details"
CHANGE_DATE = "effective_from"
CANCEL_SCHEDULED = "cancel_scheduled"
_ALT_HEAT_COST_DOMAINS = ["sensor", "input_number"]

# What a new install starts the bill details at: nothing is charged until the user says so.
SETUP_BILL_DEFAULTS: dict[str, Any] = {
    CONF_BASE_RATE_NAME: DEFAULT_BASE_RATE_NAME,
    CONF_BILL_START_DAY: DEFAULT_BILL_START_DAY,
    CONF_STANDING_CHARGE: 0.0,
    CONF_PSO_LEVY: 0.0,
    CONF_VAT_RATE: 0.0,
    CONF_DISCOUNT_RATE: 0.0,
}


def _value(ctx: PageContext, key: str) -> Any:
    """What a field starts at: in force, else the default the engine uses."""
    return ctx.current.get(key, KEY_DEFAULTS.get(key))


def optional_key(ctx: PageContext, key: str) -> vol.Optional:
    """Optional key that suggests a saved value but has no default when empty.

    An empty-string default fails EntitySelector and SelectSelector validation, and a default
    would bring an emptied field back.
    """
    current = ctx.current.get(key)
    if current:
        return vol.Optional(key, description={"suggested_value": current})
    return vol.Optional(key)


def _currency(ctx: PageContext) -> str:
    """The currency of the price fields: the saved one, else the one Home Assistant uses."""
    saved = ctx.pending.get(CONF_CURRENCY) or ctx.current.get(CONF_CURRENCY)
    return currency_code(saved or ctx.home_currency)


# ── Tariff ────────────────────────────────────────────────────────────────────


def bill_schema(ctx: PageContext) -> vol.Schema:
    """Currency, base rate name, bill start day, standing charge, levy, VAT and discount."""
    setup = ctx.mode is Mode.SETUP
    start = SETUP_BILL_DEFAULTS if setup else {}
    currency = _currency(ctx)

    def default(key: str) -> Any:
        return start[key] if key in start else _value(ctx, key)

    return vol.Schema(
        {
            vol.Required(CONF_CURRENCY, default=currency): currency_selector(),
            vol.Optional(
                CONF_BASE_RATE_NAME, default=str(default(CONF_BASE_RATE_NAME))
            ): selector.TextSelector(),
            vol.Required(
                CONF_BILL_START_DAY, default=default(CONF_BILL_START_DAY)
            ): number_selector(CONF_BILL_START_DAY),
            vol.Required(
                CONF_STANDING_CHARGE, default=default(CONF_STANDING_CHARGE)
            ): price_selector(CONF_STANDING_CHARGE, currency),
            vol.Required(CONF_PSO_LEVY, default=default(CONF_PSO_LEVY)): price_selector(
                CONF_PSO_LEVY, currency
            ),
            vol.Required(CONF_VAT_RATE, default=default(CONF_VAT_RATE)): number_selector(
                CONF_VAT_RATE
            ),
            vol.Required(
                CONF_DISCOUNT_RATE, default=default(CONF_DISCOUNT_RATE)
            ): number_selector(CONF_DISCOUNT_RATE),
        }
    )


def _suggest(key: str, value: float | None) -> vol.Required:
    """A required field that starts at *value* when there is one, and is empty otherwise.

    A suggested value is shown but is not a default, so the field still has to be filled in.
    """
    if value is None:
        return vol.Required(key)
    return vol.Required(key, description={"suggested_value": value})


def tariff_schema(ctx: PageContext) -> vol.Schema:
    """Base rate, export rate and how many time-of-day rates there are.

    Setup has no defaults for the two rates and carries the bill details in a collapsed
    section. Configure pre-fills the rates and the count. Its tariff menu opens the other
    screens.
    """
    currency = _currency(ctx)
    if ctx.mode is Mode.SETUP:
        offered = rate_prefill(ctx.rate_defaults)
        return vol.Schema(
            {
                _suggest(CONF_BASE_RATE, offered.day_rate): price_selector(
                    CONF_BASE_RATE, currency
                ),
                _suggest(CONF_EXPORT_RATE, offered.export_rate): price_selector(
                    CONF_EXPORT_RATE, currency
                ),
                vol.Required("rate_count", default="0"): rate_count_selector(),
                vol.Optional(BILL_SECTION): section(bill_schema(ctx), {"collapsed": True}),
            }
        )
    saved = str(rate_count(ctx.current.get(CONF_RATE_PERIODS)))
    return vol.Schema(
        {
            vol.Required(
                CONF_BASE_RATE, default=float(_value(ctx, CONF_BASE_RATE))
            ): price_selector(CONF_BASE_RATE, currency),
            vol.Required(
                CONF_EXPORT_RATE, default=float(_value(ctx, CONF_EXPORT_RATE))
            ): price_selector(CONF_EXPORT_RATE, currency),
            vol.Required("rate_count", default=saved): rate_count_selector(),
        }
    )


def _rate_row_section(row: dict[str, Any], currency: str) -> object:
    """One rate row: name, rate, start and end. A new row has no rate to suggest."""
    saved = row["rate"]
    rate_key = vol.Required("rate", default=saved) if saved is not None else vol.Required("rate")
    return section(
        vol.Schema(
            {
                vol.Required("name", default=row["name"]): selector.TextSelector(),
                rate_key: price_selector(CONF_BASE_RATE, currency),
                vol.Required("start", default=row["start"]): selector.TimeSelector(),
                vol.Required("end", default=row["end"]): selector.TimeSelector(),
            }
        ),
        {"collapsed": False},
    )


def rates_schema(ctx: PageContext, count: int, country: str | None) -> vol.Schema:
    """Exactly *count* rows. Saved rows first, then new ones. Fewer rows drops the last."""
    saved = ctx.current.get(CONF_RATE_PERIODS) or []
    night = rate_prefill(ctx.rate_defaults).night_rate if ctx.mode is Mode.SETUP else None
    rows = default_rate_rows(count, saved, night_window(country), night)
    currency = _currency(ctx)
    return vol.Schema(
        {
            vol.Optional(f"rate_period_{i}"): _rate_row_section(row, currency)
            for i, row in enumerate(rows, 1)
        }
    )


def schedule_schema(ctx: PageContext) -> vol.Schema:
    """The date a dated rate change starts, and a way to cancel the ones scheduled."""
    fields: dict = {vol.Optional(CHANGE_DATE): selector.DateSelector()}
    if scheduled_tariff_changes(dict(ctx.current), ctx.today):
        fields[vol.Optional(CANCEL_SCHEDULED, default=False)] = selector.BooleanSelector()
    return vol.Schema(fields)


# ── Battery, forecast, hot water, EV ──────────────────────────────────────────


def _month_values(ctx: PageContext, key: str) -> list[str]:
    """The months in force for a season list, as the strings the selector holds.

    What the user saved, else the defaults for Home Assistant's latitude. Nothing is saved
    until the user edits the list.
    """
    months = ctx.current.get(key)
    if months is None:
        months = season_defaults(ctx.latitude)[key]
    return [str(month) for month in sorted(months)]


def battery_schema(ctx: PageContext) -> vol.Schema:
    """Capacity, inverter output, cost and throughput budget."""
    currency = _currency(ctx)
    return vol.Schema(
        {
            vol.Optional(
                CONF_BATTERY_CAPACITY, default=float(_value(ctx, CONF_BATTERY_CAPACITY))
            ): number_selector(CONF_BATTERY_CAPACITY),
            vol.Optional(
                CONF_INVERTER_MAX_OUTPUT, default=float(_value(ctx, CONF_INVERTER_MAX_OUTPUT))
            ): number_selector(CONF_INVERTER_MAX_OUTPUT),
            vol.Optional(
                CONF_BATTERY_COST, default=float(_value(ctx, CONF_BATTERY_COST))
            ): battery_cost_selector(currency),
            vol.Optional(
                CONF_BATTERY_THROUGHPUT_BUDGET,
                default=float(_value(ctx, CONF_BATTERY_THROUGHPUT_BUDGET)),
            ): number_selector(CONF_BATTERY_THROUGHPUT_BUDGET),
        }
    )


def charge_planning_schema(ctx: PageContext) -> vol.Schema:
    """Minimum charge, overnight cap, the winter and shoulder months and winter behaviour."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_BATTERY_MIN_SOC, default=_value(ctx, CONF_BATTERY_MIN_SOC)
            ): number_selector(CONF_BATTERY_MIN_SOC),
            vol.Optional(
                CONF_OVERNIGHT_CHARGE_TARGET, default=_value(ctx, CONF_OVERNIGHT_CHARGE_TARGET)
            ): number_selector(CONF_OVERNIGHT_CHARGE_TARGET),
            vol.Optional(
                CONF_CHARGE_WINTER_MONTHS, default=_month_values(ctx, CONF_CHARGE_WINTER_MONTHS)
            ): months_selector(),
            vol.Optional(
                CONF_CHARGE_SHOULDER_MONTHS,
                default=_month_values(ctx, CONF_CHARGE_SHOULDER_MONTHS),
            ): months_selector(),
            vol.Optional(
                CONF_CHARGE_WINTER_USES_FORECAST,
                default=bool(ctx.current.get(CONF_CHARGE_WINTER_USES_FORECAST, False)),
            ): selector.BooleanSelector(),
        }
    )


def forecast_schema(ctx: PageContext) -> vol.Schema:
    """The forecast, pessimistic forecast, day after tomorrow and carbon intensity sensors."""
    return vol.Schema(
        {
            optional_key(ctx, key): entity_selector()
            for key in (
                CONF_FORECAST_ENTITY,
                CONF_FORECAST_ENTITY_P10,
                CONF_FORECAST_ENTITY_D2,
                CONF_CARBON_INTENSITY_ENTITY,
            )
        }
    )


def alt_heat_schema(ctx: PageContext) -> vol.Schema:
    """On or off, a label, what the cost is of, the cost and a sensor for it."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_ALT_HEAT_ENABLED, default=bool(_value(ctx, CONF_ALT_HEAT_ENABLED))
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ALT_HEAT_LABEL,
                default=str(ctx.current.get(CONF_ALT_HEAT_LABEL, DEFAULT_ALT_HEAT_LABEL)),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_ALT_HEAT_COST_UNIT,
                default=str(ctx.current.get(CONF_ALT_HEAT_COST_UNIT, DEFAULT_ALT_HEAT_UNIT)),
            ): alt_heat_unit_selector(),
            optional_key(ctx, CONF_ALT_HEAT_COST): number_selector(
                CONF_ALT_HEAT_COST, _currency(ctx)
            ),
            optional_key(ctx, CONF_ALT_HEAT_COST_ENTITY): entity_selector(_ALT_HEAT_COST_DOMAINS),
        }
    )


def hot_water_schema(ctx: PageContext) -> vol.Schema:
    """The immersion switch and sensor, element power, longest run, ready-by times and alternative
    heating."""
    wattage = ctx.current.get(CONF_IMMERSION_WATTAGE, DEFAULT_IMMERSION_WATTAGE)
    max_run = ctx.current.get(CONF_IMMERSION_MAX_RUN_MINUTES, DEFAULT_IMMERSION_MAX_RUN_MINUTES)
    enabled = bool(ctx.current.get(CONF_ALT_HEAT_ENABLED))
    return vol.Schema(
        {
            optional_key(ctx, CONF_IMMERSION_SWITCH): entity_selector("switch"),
            optional_key(ctx, CONF_IMMERSION_TEMP_SENSOR): entity_selector(),
            vol.Optional(CONF_IMMERSION_WATTAGE, default=float(wattage)): number_selector(
                CONF_IMMERSION_WATTAGE
            ),
            vol.Optional(CONF_IMMERSION_MAX_RUN_MINUTES, default=float(max_run)): number_selector(
                CONF_IMMERSION_MAX_RUN_MINUTES
            ),
            optional_key(ctx, CONF_IMMERSION_READY_TIMES): selector.TextSelector(
                selector.TextSelectorConfig(multiple=True)
            ),
            vol.Optional(ALT_HEAT_SECTION): section(
                alt_heat_schema(ctx), {"collapsed": not enabled}
            ),
        }
    )


def ev_schema(ctx: PageContext) -> vol.Schema:
    """The car efficiency. The charger itself is found automatically."""
    efficiency = ctx.current.get(
        CONF_CAR_EFFICIENCY_KWH_PER_100KM, DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM
    )
    return vol.Schema(
        {
            vol.Optional(
                CONF_CAR_EFFICIENCY_KWH_PER_100KM, default=float(efficiency)
            ): number_selector(CONF_CAR_EFFICIENCY_KWH_PER_100KM)
        }
    )

