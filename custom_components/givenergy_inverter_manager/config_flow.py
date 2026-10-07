"""
config_flow.py — Setup and options flow for GivEnergy Inverter Manager.

Setup wizard steps:
  1. inverter   — auto-discovers GivTCP entities. When fully detected,
                  shows only battery capacity and max output to confirm.
                  Falls back to manual entity entry if discovery fails.
  2. tariff     — rate periods, export rate, standing charge, etc.
                  Also shows a summary of discovered scheduling entities.
  3. forecast   — optional Forecast.Solar or Solcast integration.
  4. immersion  — optional immersion heater.
  5. ev         — optional EV charger.
  6. battery    — overnight charge thresholds.
  7. confirm    — read-only summary, submit to create the entry.

Options flow: edit tariff and thresholds without reinstalling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .config_helpers import effective_config
from .const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_BILL_START_DAY,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_DRY_RUN,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_EXPORT_RATE,
    CONF_FORECAST_CONSERVATISM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_PROVIDER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SOLAR_POWER,
    CONF_STANDING_CHARGE,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CONF_TARGET_SOC_ENTITY,
    CONF_VAT_RATE,
    CONF_VERBOSE_LOGGING,
    CURRENCIES,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_COST,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_THROUGHPUT_BUDGET,
    DEFAULT_BILL_START_DAY,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_CHEAP_RATE_FLOOR_SOC,
    DEFAULT_CURRENCY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_DRY_RUN,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FORECAST_CONSERVATISM,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_TARGET_TEMP,
    DEFAULT_IMMERSION_WATTAGE,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DEFAULT_PSO_LEVY,
    DEFAULT_RATE_PERIODS,
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_VAT_RATE,
    DEFAULT_VERBOSE_LOGGING,
    DOMAIN,
    FORECAST_PROVIDER_FORECAST_SOLAR,
    FORECAST_PROVIDER_SOLCAST,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from .core.tariff import (
    TariffSubmission,
    build_tariff,
    options_after_reconfigure,
    options_after_tariff_save,
    scheduled_tariff_changes,
    tariff_in_force,
)
from .discovery import discover_ev_chargers, discover_givtcp_inverters

_LOGGER = logging.getLogger(__name__)

_MANUAL = "__manual__"

# Maps discover_givtcp_inverters() entity keys → config entry keys (CONF_* constants).
_DISCOVERY_TO_CONF: dict[str, str] = {
    "solar_power": CONF_SOLAR_POWER,
    "battery_soc": CONF_BATTERY_SOC,
    "battery_power": CONF_BATTERY_POWER,
    "grid_power": CONF_GRID_POWER,
    "house_load": CONF_HOUSE_LOAD,
    "inverter_temp": CONF_INVERTER_TEMP_ENTITY,
    "target_soc": CONF_TARGET_SOC_ENTITY,
    "enable_charge_target": CONF_ENABLE_CHARGE_TARGET,
    "enable_charge_schedule": CONF_ENABLE_CHARGE_SCHEDULE,
    "charge_start_time": CONF_CHARGE_START_TIME_ENTITY,
    "charge_end_time": CONF_CHARGE_END_TIME_ENTITY,
}

_CHARGE_SCHEDULING_CONF_KEYS = [
    CONF_TARGET_SOC_ENTITY,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
]


_MAX_RATE_PERIODS = 5


@dataclass(frozen=True)
class _Bounds:
    """Range, step and unit of one number field."""

    low: float
    high: float
    step: float
    unit: str | None = None
    mode: str | None = None


# Shared by the setup wizard and the options form, so a bound changes in one place.
_NUMBER_BOUNDS: dict[str, _Bounds] = {
    CONF_BASE_RATE: _Bounds(0, 5, 0.001),
    CONF_EXPORT_RATE: _Bounds(0, 1, 0.001),
    CONF_STANDING_CHARGE: _Bounds(0, 5, 0.001),
    CONF_PSO_LEVY: _Bounds(0, 20, 0.01),
    CONF_VAT_RATE: _Bounds(0, 30, 0.1, "%"),
    CONF_DISCOUNT_RATE: _Bounds(0, 20, 0.1, "%"),
    CONF_BILL_START_DAY: _Bounds(1, 28, 1),
    CONF_BATTERY_MIN_SOC: _Bounds(5, 30, 1, "%"),
    CONF_CHEAP_RATE_FLOOR_SOC: _Bounds(0, 80, 5, "%"),
    CONF_OVERNIGHT_CHARGE_TARGET: _Bounds(20, 100, 1, "%"),
    CONF_SKIP_CHARGE_SOC_THRESHOLD: _Bounds(20, 100, 1, "%"),
    CONF_SURPLUS_DIVERT_SOC: _Bounds(50, 100, 5, "%"),
    CONF_SURPLUS_DIVERT_MIN_W: _Bounds(100, 2000, 100, "W"),
    CONF_BATTERY_COST: _Bounds(0, 20000, 100),
    CONF_BATTERY_THROUGHPUT_BUDGET: _Bounds(0, 50, 0.5, "kWh"),
    CONF_FORECAST_CONSERVATISM: _Bounds(0.0, 1.0, 0.05, mode="slider"),
    CONF_BATTERY_CAPACITY: _Bounds(1, 100, 0.1, "kWh"),
    CONF_INVERTER_MAX_OUTPUT: _Bounds(1, 20, 0.1, "kW"),
    CONF_IMMERSION_WATTAGE: _Bounds(500, 6000, 100, "W"),
    CONF_IMMERSION_TARGET_TEMP: _Bounds(40, 75, 1, "°C"),
    CONF_IMMERSION_MIN_TEMP: _Bounds(30, 60, 1, "°C"),
    CONF_CAR_EFFICIENCY_KWH_PER_100KM: _Bounds(5, 40, 0.1, "kWh/100km"),
}

# What each price field is quoted per. The currency code comes from the form.
_PRICE_PER: dict[str, str] = {
    CONF_BASE_RATE: "kWh",
    CONF_EXPORT_RATE: "kWh",
    CONF_STANDING_CHARGE: "day",
    CONF_PSO_LEVY: "month",
}


def _number_selector(key: str, unit: str | None = None) -> selector.NumberSelector:
    """Number selector for *key*, using *unit* in place of the table unit when given."""
    bounds = _NUMBER_BOUNDS[key]
    config: dict[str, Any] = {"min": bounds.low, "max": bounds.high, "step": bounds.step}
    if unit or bounds.unit:
        config["unit_of_measurement"] = unit or bounds.unit
    if bounds.mode:
        config["mode"] = bounds.mode
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _price_selector(key: str, currency: object) -> selector.NumberSelector:
    """Number selector for a price field, with the unit following *currency*."""
    return _number_selector(key, _money_unit(currency, _PRICE_PER[key]))


def _entity_selector(domain: str = "sensor") -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _forecast_provider_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=FORECAST_PROVIDER_FORECAST_SOLAR, label="Forecast.Solar"
                ),
                selector.SelectOptionDict(value=FORECAST_PROVIDER_SOLCAST, label="Solcast"),
            ]
        )
    )


def _currency_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=code, label=f"{code} ({symbol})")
                for code, symbol in CURRENCIES.items()
            ]
        )
    )


def _ordinal(day: int) -> str:
    """Return 1 as '1st', 16 as '16th'."""
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _tariff_summary(cfg: dict) -> str:
    """One paragraph stating the cheapest rate and the billing period for *cfg*."""
    try:
        tariff = build_tariff(cfg)
    except (TypeError, ValueError):
        return ""
    cheapest = tariff.get_cheapest_rate()
    if any(cheapest is p for p in tariff.rate_periods):
        window = f"{cheapest.start:%H:%M} to {cheapest.end:%H:%M}"
    else:
        window = "all day"
    code = cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    start = tariff.bill_start_day
    if start == 1:
        bill = "Your bill runs from the 1st to the last day of the month."
    else:
        bill = f"Your bill runs from the {_ordinal(start)} to the {_ordinal(start - 1)}."
    return (
        f"Cheapest rate in your saved tariff: {cheapest.name} at {cheapest.rate:.4f} "
        f"{code}/kWh, {window}. {bill}"
    )


def _periods_text(periods: list[dict]) -> str:
    """The timed rates as one line, such as Night 0.1644 (23:00 to 08:00)."""
    return ", ".join(
        f"{p['name']} {float(p['rate']):.4f} ({p['start']} to {p['end']})" for p in periods
    )


def _scheduled_changes_summary(cfg: dict, today: date) -> str:
    """One line for each rate change that has not started yet, or an empty string."""
    code = cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    lines = []
    for change in scheduled_tariff_changes(cfg, today):
        rates = change.rates
        lines.append(
            f"From {change.effective.isoformat()}: {rates[CONF_BASE_RATE_NAME]} "
            f"{float(rates[CONF_BASE_RATE]):.4f}, export {float(rates[CONF_EXPORT_RATE]):.4f} "
            f"{code}/kWh, timed rates: {_periods_text(rates[CONF_RATE_PERIODS]) or 'none'}."
        )
    if not lines:
        return ""
    return "Scheduled rate changes:\n" + "\n".join(f"- {line}" for line in lines)


def _setup_summary(data: dict) -> str:
    """Bullet list of the choices made so far, shown before the entry is created."""
    periods = _periods_text(data.get(CONF_RATE_PERIODS) or [])
    lines = [
        _tariff_summary(data),
        f"Base rate: {data.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)} "
        f"{float(data.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)):.4f}. "
        f"Timed rates: {periods or 'none'}.",
        f"Battery {float(data.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY)):g} kWh, "
        f"inverter {float(data.get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT)):g} kW.",
        f"Forecast sensor: {data.get(CONF_FORECAST_ENTITY) or 'none, a seasonal estimate is used'}.",
        f"Immersion switch: {data.get(CONF_IMMERSION_SWITCH) or 'none'}.",
    ]
    return "\n".join(f"- {line}" for line in lines if line)


def _hhmmss(hhmm: str) -> str:
    """Ensure a time string is HH:MM:SS (append :00 when only HH:MM is stored)."""
    return hhmm if len(hhmm) > 5 else hhmm + ":00"


def _periods_to_slot_defaults(periods: list[dict]) -> list[dict]:
    """Pad/trim stored rate periods to exactly _MAX_RATE_PERIODS slot dicts."""
    slots = []
    for i in range(_MAX_RATE_PERIODS):
        if i < len(periods):
            p = periods[i]
            slots.append(
                {
                    "name": p["name"],
                    "rate": float(p["rate"]),
                    "start": _hhmmss(p["start"]),
                    "end": _hhmmss(p["end"]),
                }
            )
        else:
            slots.append({"name": "", "rate": 0.0, "start": "00:00:00", "end": "00:00:00"})
    return slots


def _slots_to_rate_periods(user_input: dict) -> list[dict]:
    """Convert rate_period_N section dicts back to the stored list[dict] format."""
    periods = []
    for i in range(1, _MAX_RATE_PERIODS + 1):
        slot = user_input.get(f"rate_period_{i}") or {}
        name = (slot.get("name") or "").strip()
        if not name:
            continue
        periods.append(
            {
                "name": name,
                "rate": float(slot.get("rate") or 0.0),
                "start": (slot.get("start") or "00:00:00")[:5],  # strip :SS
                "end": (slot.get("end") or "00:00:00")[:5],
            }
        )
    return periods


def _has_rate_period_sections(user_input: dict) -> bool:
    """True when the submission carries any rate_period_N section, filled in or empty."""
    return any(f"rate_period_{i}" in user_input for i in range(1, _MAX_RATE_PERIODS + 1))


def _rate_period_errors(periods: list[dict], base_rate_name: str = "") -> dict[str, str]:
    """Return form errors for rate periods that cannot work, or an empty dict."""
    if any(p["start"] == p["end"] for p in periods):
        return {"base": "rate_period_zero_length"}
    names = [p["name"].casefold() for p in periods]
    base = (base_rate_name or "").strip().casefold()
    if base:
        names.append(base)
    if len(names) != len(set(names)):
        return {"base": "rate_period_duplicate_name"}
    return {}


def _base_rate_name(values: dict) -> str:
    """The base rate name submitted in a tariff form."""
    return str(values.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME))


def _tariff_updates(values: dict, rate_periods: list[dict]) -> dict[str, Any]:
    """Parse a submitted tariff form into the values that are stored."""
    return {
        CONF_RATE_PERIODS: rate_periods,
        CONF_BASE_RATE: float(values[CONF_BASE_RATE]),
        CONF_BASE_RATE_NAME: _base_rate_name(values),
        CONF_EXPORT_RATE: float(values[CONF_EXPORT_RATE]),
        CONF_STANDING_CHARGE: float(values[CONF_STANDING_CHARGE]),
        CONF_PSO_LEVY: float(values[CONF_PSO_LEVY]),
        CONF_VAT_RATE: float(values[CONF_VAT_RATE]),
        CONF_DISCOUNT_RATE: float(values[CONF_DISCOUNT_RATE]),
        CONF_BILL_START_DAY: int(values[CONF_BILL_START_DAY]),
        CONF_CURRENCY: values.get(CONF_CURRENCY, DEFAULT_CURRENCY),
    }


_TARIFF_CHANGE_SECTION = "tariff_change"


def _submitted_change(user_input: dict) -> dict:
    """The tariff_change section of a submission, empty when the client sent none."""
    return user_input.get(_TARIFF_CHANGE_SECTION) or {}


def _effective_from(change: dict) -> date | None:
    """The date the user asked the submitted rates to start, or None for now."""
    try:
        return date.fromisoformat(str(change["effective_from"]))
    except (KeyError, ValueError):
        return None


def _tariff_submission(user_input: dict, rate_periods: list[dict]) -> TariffSubmission:
    """What the submitted options form asks to do with the tariff."""
    change = _submitted_change(user_input)
    return TariffSubmission(
        updates=_tariff_updates(user_input.get("tariff_settings", {}), rate_periods),
        effective=_effective_from(change),
        cancel_scheduled=bool(change.get("cancel_scheduled")),
    )


def _change_date_errors(user_input: dict, today: date) -> dict[str, str]:
    """A rate change cannot start in the past: costs already accumulated are not recalculated."""
    effective = _effective_from(_submitted_change(user_input))
    if effective is not None and effective < today:
        return {"base": "tariff_change_date_in_past"}
    return {}


def _currency_code(code: object) -> str:
    """Return *code* when it is an offered currency, else the default currency."""
    return code if isinstance(code, str) and code in CURRENCIES else DEFAULT_CURRENCY


def _money_unit(code: object, per: str) -> str:
    """Unit text for a price field, such as GBP/kWh."""
    return f"{_currency_code(code)}/{per}"


def _rate_period_section(slot: dict, currency: object = DEFAULT_CURRENCY) -> object:
    """Return a section() for one rate-period slot pre-filled from *slot*."""
    return section(
        vol.Schema(
            {
                vol.Optional("name", default=slot["name"]): selector.TextSelector(),
                # A timed rate is bounded like the base rate.
                vol.Optional("rate", default=slot["rate"]): _price_selector(
                    CONF_BASE_RATE, currency
                ),
                vol.Optional("start", default=slot["start"]): selector.TimeSelector(),
                vol.Optional("end", default=slot["end"]): selector.TimeSelector(),
            }
        ),
        {"collapsed": not slot["name"]},
    )


def _build_charge_scheduling_summary(data: dict) -> tuple[str, str]:
    """Return (status, detail) strings for the charge scheduling step."""
    detected = sum(1 for k in _CHARGE_SCHEDULING_CONF_KEYS if data.get(k))

    if detected == 5:
        status = "[OK] All 5 scheduling entities detected - automatic overnight charging enabled"
    elif detected > 0:
        status = f"[!!] {detected}/5 scheduling entities detected - partial scheduling"
    else:
        status = "[--] No scheduling entities detected - manual charging only"

    detail_lines = [
        f"{'OK' if data.get(k) else '--'} {k}: {data.get(k) or 'not found'}"
        for k in _CHARGE_SCHEDULING_CONF_KEYS
    ]
    return status, "\n".join(detail_lines)


class GivEnergyInverterManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for GivEnergy Inverter Manager."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._discovered_inverters: list = []
        self._discovered_chargers: list = []

    def _select_best_inverter(self) -> tuple[object | None, bool]:
        """Return (best_inverter, is_auto_detected)."""
        fully_configured = [i for i in self._discovered_inverters if i.is_fully_configured]
        best_inverter = (
            fully_configured[0]
            if fully_configured
            else (self._discovered_inverters[0] if self._discovered_inverters else None)
        )
        is_auto_detected = best_inverter is not None and best_inverter.is_fully_configured
        return best_inverter, is_auto_detected

    def _build_inverter_options(
        self, best_inverter: object | None
    ) -> tuple[list[selector.SelectOptionDict], str]:
        options = [selector.SelectOptionDict(value=_MANUAL, label="Manual entry")]
        for inv in self._discovered_inverters:
            label = inv.display_name
            if not inv.is_fully_configured:
                label += " (some sensors missing)"
            options.append(selector.SelectOptionDict(value=inv.serial, label=label))
        default_inverter = best_inverter.serial if best_inverter else _MANUAL
        return options, default_inverter

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        return await self.async_step_inverter(user_input)

    async def _handle_fully_configured_inverter(
        self, inverter, user_input
    ) -> config_entries.ConfigFlowResult:
        """Handle fully configured inverter selection."""
        for disc_key, conf_key in _DISCOVERY_TO_CONF.items():
            if disc_key in inverter.entities:
                self._data[conf_key] = inverter.entities[disc_key]
        self._data[CONF_BATTERY_CAPACITY] = float(
            user_input.get(
                CONF_BATTERY_CAPACITY,
                inverter.battery_capacity_kwh or DEFAULT_BATTERY_CAPACITY,
            )
        )
        self._data[CONF_INVERTER_MAX_OUTPUT] = float(
            user_input.get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT)
        )
        self._data[CONF_INVERTER_SERIAL] = inverter.serial
        await self.async_set_unique_id(inverter.serial)
        self._abort_if_unique_id_configured()
        return await self.async_step_tariff()

    def _handle_partial_inverter(self, inverter, user_input) -> None:
        """Fill partial inverter discovery results."""
        for disc_key, conf_key in _DISCOVERY_TO_CONF.items():
            if disc_key in inverter.entities:
                user_input[conf_key] = inverter.entities[disc_key]

    @staticmethod
    def _manual_path_errors(user_input) -> dict[str, str]:
        """Return form errors when a required manual entity is missing."""
        required = [
            CONF_SOLAR_POWER,
            CONF_BATTERY_SOC,
            CONF_BATTERY_POWER,
            CONF_GRID_POWER,
            CONF_HOUSE_LOAD,
        ]
        if any(not user_input.get(k) for k in required):
            return {"base": "missing_entities"}
        return {}

    async def _finish_manual_path(self, user_input) -> config_entries.ConfigFlowResult:
        """Store the manually selected entities and move to the tariff step."""
        self._data.update(user_input)
        serial = user_input.get("discovered_inverter", "manual")
        self._data[CONF_INVERTER_SERIAL] = serial
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()

        return await self.async_step_tariff()

    def _build_auto_detected_schema(self, best_inverter, inverter_options) -> vol.Schema:
        """Build schema for auto-detected inverter."""
        default_capacity = best_inverter.battery_capacity_kwh or DEFAULT_BATTERY_CAPACITY
        return vol.Schema(
            {
                vol.Optional(
                    "discovered_inverter", default=best_inverter.serial
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=inverter_options)),
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=default_capacity
                ): _number_selector(CONF_BATTERY_CAPACITY),
                vol.Optional(
                    CONF_INVERTER_MAX_OUTPUT, default=DEFAULT_INVERTER_MAX_OUTPUT
                ): _number_selector(CONF_INVERTER_MAX_OUTPUT),
            }
        )

    def _build_manual_schema(self, default_capacity, inverter_options) -> vol.Schema:
        """Build schema for manual entity selection."""
        return vol.Schema(
            {
                vol.Optional(
                    "discovered_inverter", default=inverter_options[0]["value"]
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=inverter_options)),
                vol.Required(CONF_SOLAR_POWER): _entity_selector(),
                vol.Required(CONF_BATTERY_SOC): _entity_selector(),
                vol.Required(CONF_BATTERY_POWER): _entity_selector(),
                vol.Required(CONF_GRID_POWER): _entity_selector(),
                vol.Required(CONF_HOUSE_LOAD): _entity_selector(),
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=default_capacity
                ): _number_selector(CONF_BATTERY_CAPACITY),
                vol.Optional(
                    CONF_INVERTER_MAX_OUTPUT, default=DEFAULT_INVERTER_MAX_OUTPUT
                ): _number_selector(CONF_INVERTER_MAX_OUTPUT),
            }
        )

    async def async_step_inverter(self, user_input=None) -> config_entries.ConfigFlowResult:
        """
        Step 1: Inverter selection.

        When GivTCP auto-detects the inverter with all 5 required power sensors,
        this step shows only battery capacity and max output to confirm — the
        entity IDs are silently filled in from discovery.

        Falls back to the full entity-selector form if discovery is incomplete.
        """
        errors: dict[str, str] = {}
        all_states = {s.entity_id: s for s in self.hass.states.async_all()}
        self._discovered_inverters = discover_givtcp_inverters(all_states)
        best_inverter, is_auto_detected = self._select_best_inverter()

        if user_input is not None:
            selected_serial = user_input.get("discovered_inverter", _MANUAL)

            if selected_serial != _MANUAL:
                inverter = next(
                    (i for i in self._discovered_inverters if i.serial == selected_serial), None
                )
                if inverter and inverter.is_fully_configured:
                    return await self._handle_fully_configured_inverter(inverter, user_input)
                if inverter:
                    self._handle_partial_inverter(inverter, user_input)

            errors = self._manual_path_errors(user_input)
            if not errors:
                return await self._finish_manual_path(user_input)

        if is_auto_detected:
            return self._show_auto_detected_form(best_inverter, errors)
        return self._show_manual_form(best_inverter, errors)

    def _show_auto_detected_form(
        self, best_inverter, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Show the confirm form for an inverter whose sensors were all detected."""
        inverter_options, _default = self._build_inverter_options(best_inverter)
        return self.async_show_form(
            step_id="inverter",
            data_schema=self._build_auto_detected_schema(best_inverter, inverter_options),
            errors=errors,
            description_placeholders={
                "status": f"All sensors detected for {best_inverter.display_name}",
                "discovered_count": str(len(self._discovered_inverters)),
            },
        )

    def _show_manual_form(
        self, best_inverter, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Show the entity-selector form, used when discovery found nothing complete."""
        inverter_options, _default = self._build_inverter_options(best_inverter)
        default_capacity = (
            best_inverter.battery_capacity_kwh if best_inverter else None
        ) or DEFAULT_BATTERY_CAPACITY
        return self.async_show_form(
            step_id="inverter",
            data_schema=self._build_manual_schema(default_capacity, inverter_options),
            errors=errors,
            description_placeholders={"discovered_count": str(len(self._discovered_inverters))},
        )

    async def async_step_tariff(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 2: Tariff configuration, with scheduling discovery summary."""
        errors: dict[str, str] = {}
        if user_input is not None:
            periods = _slots_to_rate_periods(user_input)
            errors = _rate_period_errors(periods, _base_rate_name(user_input))
            if not errors:
                self._data.update(_tariff_updates(user_input, periods))
                return await self.async_step_forecast()
        return self._show_tariff_form(user_input, errors)

    def _show_tariff_form(
        self, user_input: dict | None, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Show the tariff form, re-suggesting the submitted values after an error."""
        currency = (user_input or {}).get(CONF_CURRENCY) or self._data.get(CONF_CURRENCY)
        schema = self._build_tariff_schema(currency=currency)
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        scheduling_status, scheduling_detail = _build_charge_scheduling_summary(self._data)
        return self.async_show_form(
            step_id="tariff",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "scheduling_status": scheduling_status,
                "scheduling_detail": scheduling_detail,
            },
        )

    @staticmethod
    def _build_tariff_schema(
        periods: list[dict] | None = None,
        values: dict | None = None,
        currency: str | None = None,
    ) -> vol.Schema:
        """Build the tariff form. Price units follow *currency*, else the saved currency."""
        values = values or {}
        currency = currency or values.get(CONF_CURRENCY)
        slots = _periods_to_slot_defaults(periods if periods is not None else DEFAULT_RATE_PERIODS)
        schema_dict: dict = {
            vol.Required(
                CONF_BASE_RATE, default=values.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)
            ): _price_selector(CONF_BASE_RATE, currency),
            vol.Optional(
                CONF_BASE_RATE_NAME, default=values.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
            ): selector.TextSelector(),
            vol.Required(
                CONF_EXPORT_RATE, default=values.get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE)
            ): _price_selector(CONF_EXPORT_RATE, currency),
            vol.Required(
                CONF_STANDING_CHARGE,
                default=values.get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
            ): _price_selector(CONF_STANDING_CHARGE, currency),
            vol.Required(
                CONF_PSO_LEVY, default=values.get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)
            ): _price_selector(CONF_PSO_LEVY, currency),
            vol.Required(
                CONF_VAT_RATE, default=values.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
            ): _number_selector(CONF_VAT_RATE),
            vol.Required(
                CONF_DISCOUNT_RATE, default=values.get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE)
            ): _number_selector(CONF_DISCOUNT_RATE),
            vol.Required(
                CONF_BILL_START_DAY, default=values.get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY)
            ): _number_selector(CONF_BILL_START_DAY),
            vol.Required(
                CONF_CURRENCY, default=values.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            ): _currency_selector(),
        }
        for i, slot in enumerate(slots, 1):
            schema_dict[vol.Optional(f"rate_period_{i}")] = _rate_period_section(slot, currency)
        return vol.Schema(schema_dict)

    async def async_step_forecast(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 3: Solar forecast integration (optional)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_immersion()
        schema = vol.Schema(
            {
                vol.Optional(CONF_FORECAST_PROVIDER): _forecast_provider_selector(),
                vol.Optional(CONF_FORECAST_ENTITY): _entity_selector(),
                vol.Optional(CONF_FORECAST_ENTITY_P10): _entity_selector(),
                vol.Optional(CONF_FORECAST_ENTITY_D2): _entity_selector(),
                vol.Optional(CONF_CARBON_INTENSITY_ENTITY): _entity_selector(),
                vol.Optional(
                    CONF_FORECAST_CONSERVATISM, default=DEFAULT_FORECAST_CONSERVATISM
                ): _number_selector(CONF_FORECAST_CONSERVATISM),
            }
        )
        return self.async_show_form(step_id="forecast", data_schema=schema)

    async def async_step_immersion(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 4: Immersion heater (optional)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_ev()
        schema = vol.Schema(
            {
                vol.Optional(CONF_IMMERSION_SWITCH): _entity_selector("switch"),
                vol.Optional(
                    CONF_IMMERSION_WATTAGE, default=DEFAULT_IMMERSION_WATTAGE
                ): _number_selector(CONF_IMMERSION_WATTAGE),
                vol.Optional(CONF_IMMERSION_TEMP_SENSOR): _entity_selector(),
                vol.Optional(
                    CONF_IMMERSION_TARGET_TEMP, default=DEFAULT_IMMERSION_TARGET_TEMP
                ): _number_selector(CONF_IMMERSION_TARGET_TEMP),
                vol.Optional(
                    CONF_IMMERSION_MIN_TEMP, default=DEFAULT_IMMERSION_MIN_TEMP
                ): _number_selector(CONF_IMMERSION_MIN_TEMP),
            }
        )
        return self.async_show_form(step_id="immersion", data_schema=schema)

    async def async_step_ev(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 5: EV charger (optional). Auto-discovers Zappi, Wallbox, OCPP, Ohme, Easee."""
        all_states = {s.entity_id: s for s in self.hass.states.async_all()}
        self._discovered_chargers = discover_ev_chargers(all_states)

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery()

        charger_options, default_charger = self._build_charger_options()
        schema = vol.Schema(
            {
                vol.Optional(
                    "discovered_charger", default=default_charger
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=charger_options)),
                vol.Optional(
                    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
                    default=DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
                ): _number_selector(CONF_CAR_EFFICIENCY_KWH_PER_100KM),
            }
        )
        return self.async_show_form(
            step_id="ev",
            data_schema=schema,
            errors={},
            description_placeholders={"discovered_count": str(len(self._discovered_chargers))},
        )

    def _build_charger_options(self) -> tuple[list[selector.SelectOptionDict], str]:
        """Return the charger choices and the one preselected."""
        manual_ev = "__manual_ev__"
        options = [selector.SelectOptionDict(value=manual_ev, label="None / Manual entry")]
        for charger in self._discovered_chargers:
            options.append(
                selector.SelectOptionDict(value=charger.serial, label=charger.display_name)
            )
        only_charger = len(self._discovered_chargers) == 1
        return options, self._discovered_chargers[0].serial if only_charger else manual_ev

    async def async_step_battery(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 6: Battery management thresholds."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_confirm()
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BATTERY_MIN_SOC, default=DEFAULT_BATTERY_MIN_SOC
                ): _number_selector(CONF_BATTERY_MIN_SOC),
                vol.Optional(
                    CONF_CHEAP_RATE_FLOOR_SOC, default=DEFAULT_CHEAP_RATE_FLOOR_SOC
                ): _number_selector(CONF_CHEAP_RATE_FLOOR_SOC),
                vol.Optional(
                    CONF_OVERNIGHT_CHARGE_TARGET, default=DEFAULT_OVERNIGHT_CHARGE_TARGET
                ): _number_selector(CONF_OVERNIGHT_CHARGE_TARGET),
                vol.Optional(
                    CONF_SKIP_CHARGE_SOC_THRESHOLD, default=DEFAULT_SKIP_CHARGE_SOC_THRESHOLD
                ): _number_selector(CONF_SKIP_CHARGE_SOC_THRESHOLD),
                vol.Optional(
                    CONF_SURPLUS_DIVERT_SOC, default=SURPLUS_DIVERT_SOC_THRESHOLD
                ): _number_selector(CONF_SURPLUS_DIVERT_SOC),
                vol.Optional(
                    CONF_SURPLUS_DIVERT_MIN_W, default=SURPLUS_DIVERT_MIN_POWER_W
                ): _number_selector(CONF_SURPLUS_DIVERT_MIN_W),
            }
        )
        return self.async_show_form(step_id="battery", data_schema=schema)

    async def async_step_confirm(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step 7: Show what will be saved, then create the entry."""
        if user_input is not None:
            return self.async_create_entry(title="GivEnergy Inverter Manager", data=self._data)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": _setup_summary(self._data)},
        )

    async def async_step_reconfigure(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Allow updating tariff settings without removing the integration.

        Shows the same form as the tariff setup step, pre-populated with the
        values in force. On submit, writes entry data and drops the saved options
        for the same keys, because options override data. The entry update listener
        reloads the integration.
        Inverter entity mappings (set during initial auto-discovery) require a
        full remove-and-re-add to change.
        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        errors: dict[str, str] = {}
        if user_input is not None:
            periods = _slots_to_rate_periods(user_input)
            errors = _rate_period_errors(periods, _base_rate_name(user_input))
            if not errors:
                self._store_reconfigured_tariff(entry, _tariff_updates(user_input, periods))
                return self.async_abort(reason="reconfigure_successful")
        return self._show_reconfigure_form(entry, user_input, errors)

    def _store_reconfigured_tariff(self, entry, updates: dict[str, Any]) -> None:
        """Write *updates* to the entry data and drop the saved options that would override them."""
        options = options_after_reconfigure(dict(entry.options), updates, dt_util.now().date())
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **updates}, options=options
        )

    def _show_reconfigure_form(
        self, entry, user_input: dict | None, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Show the tariff form filled with the values in force."""
        current = tariff_in_force(effective_config(entry), dt_util.now().date())
        schema = self.__class__._build_tariff_schema(
            current.get(CONF_RATE_PERIODS) or [],
            current,
            currency=(user_input or {}).get(CONF_CURRENCY),
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> GivEnergyOptionsFlow:
        return GivEnergyOptionsFlow(config_entry)


_OPTIONAL_FORECAST_KEYS = (
    CONF_FORECAST_PROVIDER,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_ENTITY_D2,
    CONF_CARBON_INTENSITY_ENTITY,
)

_OPTIONAL_IMMERSION_KEYS = (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)


class GivEnergyOptionsFlow(config_entries.OptionsFlow):
    """Options flow — tariff rates, per-period rates, thresholds, forecast."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    def _get(self, key, default) -> Any:
        """Return the saved option, else the setup value, else the default.

        A saved falsy option (0, an empty string, an empty list) is a real choice
        and must not fall back to the setup value.
        """
        return self._in_force().get(key, default)

    def _in_force(self) -> dict[str, Any]:
        """The saved values with the unit rates in force today: the latest dated change applied."""
        return tariff_in_force(effective_config(self._config_entry), dt_util.now().date())

    def _optional_key(self, key) -> vol.Optional:
        """Optional schema key that pre-fills a saved value but has no default when empty.

        An empty-string default fails EntitySelector and SelectSelector validation.
        """
        current = self._get(key, "")
        if current:
            return vol.Optional(key, description={"suggested_value": current})
        return vol.Optional(key)

    def _save_options(
        self, user_input: dict, rate_periods: list[dict]
    ) -> config_entries.ConfigFlowResult:
        """Store the submitted options and create the entry."""
        self._options = options_after_tariff_save(
            self._options,
            self._in_force(),
            _tariff_submission(user_input, rate_periods),
            dt_util.now().date(),
        )
        self._options.update(user_input.get("threshold_settings", {}))
        self._store_floats(
            user_input.get("hardware_settings", {}),
            (CONF_BATTERY_CAPACITY, CONF_INVERTER_MAX_OUTPUT),
        )
        self._store_optional_entities(user_input, "forecast_settings", _OPTIONAL_FORECAST_KEYS)
        self._store_floats(
            user_input.get("forecast_settings", {}), (CONF_FORECAST_CONSERVATISM,)
        )
        self._store_optional_entities(user_input, "immersion_settings", _OPTIONAL_IMMERSION_KEYS)
        self._store_floats(user_input.get("immersion_settings", {}), (CONF_IMMERSION_WATTAGE,))
        self._store_floats(
            user_input.get("ev_settings", {}), (CONF_CAR_EFFICIENCY_KWH_PER_100KM,)
        )
        return self.async_create_entry(title="", data=self._options)

    def _store_optional_entities(
        self, user_input: dict, section_name: str, keys: tuple[str, ...]
    ) -> None:
        """Store the entity choices of one submitted section.

        An entity the section leaves out was cleared by the user, so it is saved as empty.
        A section the submission does not carry at all is left as saved.
        """
        submitted = user_input.get(section_name)
        if submitted is None:
            return
        for key in keys:
            self._options[key] = submitted.get(key, "")

    def _store_floats(self, submitted: dict, keys: tuple[str, ...]) -> None:
        """Store each of *keys* that the form submitted, as a float."""
        for key in keys:
            if key in submitted:
                self._options[key] = float(submitted[key])

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Single-page options: tariff, per-period rates, thresholds, forecast."""
        errors: dict[str, str] = {}
        if user_input is not None:
            rate_periods = self._submitted_rate_periods(user_input)
            errors = self._submission_errors(user_input, rate_periods)
            if not errors:
                return self._save_options(user_input, rate_periods)
        return self._show_form(user_input, errors)

    def _submitted_rate_periods(self, user_input: dict) -> list[dict]:
        """The submitted rate periods, or the saved ones when the submission has no section.

        The form always sends the sections. A client that sends only the fields it changes
        would otherwise clear the tariff's timed rates.
        """
        if _has_rate_period_sections(user_input):
            return _slots_to_rate_periods(user_input)
        return list(self._get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS))

    @staticmethod
    def _submission_errors(user_input: dict, rate_periods: list[dict]) -> dict[str, str]:
        """Return form errors for a submitted options form, or an empty dict."""
        tariff = user_input.get("tariff_settings", {})
        return _rate_period_errors(rate_periods, _base_rate_name(tariff)) or _change_date_errors(
            user_input, dt_util.now().date()
        )

    def _show_form(
        self, user_input: dict | None, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        """Show the options form, re-suggesting the submitted values after an error."""
        schema = vol.Schema(self._form_fields())
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"tariff_summary": self._tariff_summary_text()},
        )

    def _tariff_summary_text(self) -> str:
        """The tariff in force today, then any rate change that has not started yet."""
        in_force = self._in_force()
        scheduled = _scheduled_changes_summary(in_force, dt_util.now().date())
        summary = _tariff_summary(in_force)
        return f"{summary}\n\n{scheduled}" if scheduled else summary

    def _form_fields(self) -> dict:
        """Return the options form fields in display order."""
        currency = self._get(CONF_CURRENCY, DEFAULT_CURRENCY)
        fields: dict = {vol.Required("tariff_settings"): self._tariff_section(currency)}
        fields.update(self._rate_period_sections(currency))
        fields[vol.Optional(_TARIFF_CHANGE_SECTION)] = self._tariff_change_section()
        fields[vol.Required("threshold_settings")] = self._threshold_section(currency)
        fields[vol.Required("forecast_settings")] = self._forecast_section()
        fields[vol.Required("hardware_settings")] = self._hardware_section()
        # Optional, so a client that omits the section keeps the saved devices.
        fields[vol.Optional("immersion_settings")] = self._immersion_section()
        fields[vol.Required("ev_settings")] = self._ev_section()
        return fields

    def _rate_period_sections(self, currency: object) -> dict:
        """Return one collapsible section per rate-period slot, filled from the saved periods."""
        slots = _periods_to_slot_defaults(self._get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS))
        return {
            vol.Optional(f"rate_period_{i}"): _rate_period_section(slot, currency)
            for i, slot in enumerate(slots, 1)
        }

    def _tariff_change_section(self) -> object:
        """Return the section that dates the submitted unit rates, and cancels scheduled ones.

        Optional, so a client that omits it applies the rates now and keeps what is scheduled.
        """
        fields: dict = {vol.Optional("effective_from"): selector.DateSelector()}
        if scheduled_tariff_changes(self._in_force(), dt_util.now().date()):
            fields[vol.Optional("cancel_scheduled", default=False)] = selector.BooleanSelector()
        return section(vol.Schema(fields), {"collapsed": True})

    def _tariff_section(self, currency: object) -> object:
        """Return the tariff section: base rate, export rate, charges, billing and currency."""
        return section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_RATE,
                        default=float(self._get(CONF_BASE_RATE, DEFAULT_BASE_RATE)),
                    ): _price_selector(CONF_BASE_RATE, currency),
                    vol.Optional(
                        CONF_BASE_RATE_NAME,
                        default=str(self._get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)),
                    ): selector.TextSelector(),
                    vol.Required(
                        CONF_EXPORT_RATE,
                        default=self._get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
                    ): _price_selector(CONF_EXPORT_RATE, currency),
                    vol.Required(
                        CONF_STANDING_CHARGE,
                        default=self._get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
                    ): _price_selector(CONF_STANDING_CHARGE, currency),
                    vol.Required(
                        CONF_PSO_LEVY, default=self._get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)
                    ): _price_selector(CONF_PSO_LEVY, currency),
                    vol.Required(
                        CONF_VAT_RATE, default=self._get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
                    ): _number_selector(CONF_VAT_RATE),
                    vol.Required(
                        CONF_DISCOUNT_RATE,
                        default=self._get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE),
                    ): _number_selector(CONF_DISCOUNT_RATE),
                    vol.Required(
                        CONF_BILL_START_DAY,
                        default=self._get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY),
                    ): _number_selector(CONF_BILL_START_DAY),
                    vol.Required(
                        CONF_CURRENCY, default=self._get(CONF_CURRENCY, DEFAULT_CURRENCY)
                    ): _currency_selector(),
                }
            ),
            {"collapsed": False},
        )

    def _threshold_section(self, currency: object) -> object:
        """Return the battery threshold section, plus battery cost, dry run and logging."""
        return section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_BATTERY_MIN_SOC,
                        default=self._get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC),
                    ): _number_selector(CONF_BATTERY_MIN_SOC),
                    vol.Optional(
                        CONF_CHEAP_RATE_FLOOR_SOC,
                        default=self._get(CONF_CHEAP_RATE_FLOOR_SOC, DEFAULT_CHEAP_RATE_FLOOR_SOC),
                    ): _number_selector(CONF_CHEAP_RATE_FLOOR_SOC),
                    vol.Optional(
                        CONF_OVERNIGHT_CHARGE_TARGET,
                        default=self._get(
                            CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET
                        ),
                    ): _number_selector(CONF_OVERNIGHT_CHARGE_TARGET),
                    vol.Optional(
                        CONF_SKIP_CHARGE_SOC_THRESHOLD,
                        default=self._get(
                            CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD
                        ),
                    ): _number_selector(CONF_SKIP_CHARGE_SOC_THRESHOLD),
                    vol.Optional(
                        CONF_BATTERY_COST,
                        default=float(self._get(CONF_BATTERY_COST, DEFAULT_BATTERY_COST)),
                    ): _number_selector(CONF_BATTERY_COST, CURRENCIES[_currency_code(currency)]),
                    vol.Optional(
                        CONF_BATTERY_THROUGHPUT_BUDGET,
                        default=float(
                            self._get(
                                CONF_BATTERY_THROUGHPUT_BUDGET, DEFAULT_BATTERY_THROUGHPUT_BUDGET
                            )
                        ),
                    ): _number_selector(CONF_BATTERY_THROUGHPUT_BUDGET),
                    vol.Optional(
                        CONF_DRY_RUN, default=bool(self._get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_VERBOSE_LOGGING,
                        default=bool(self._get(CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING)),
                    ): selector.BooleanSelector(),
                }
            ),
            {"collapsed": True},
        )

    def _forecast_section(self) -> object:
        """Return the forecast section: provider, forecast and carbon sensors, conservatism."""
        return section(
            vol.Schema(
                {
                    self._optional_key(CONF_FORECAST_PROVIDER): _forecast_provider_selector(),
                    self._optional_key(CONF_FORECAST_ENTITY): _entity_selector(),
                    self._optional_key(CONF_FORECAST_ENTITY_P10): _entity_selector(),
                    self._optional_key(CONF_FORECAST_ENTITY_D2): _entity_selector(),
                    self._optional_key(CONF_CARBON_INTENSITY_ENTITY): _entity_selector(),
                    vol.Optional(
                        CONF_FORECAST_CONSERVATISM,
                        default=float(
                            self._get(CONF_FORECAST_CONSERVATISM, DEFAULT_FORECAST_CONSERVATISM)
                        ),
                    ): _number_selector(CONF_FORECAST_CONSERVATISM),
                }
            ),
            {"collapsed": True},
        )

    def _hardware_section(self) -> object:
        """Return the hardware section: battery capacity and inverter output."""
        return section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_BATTERY_CAPACITY,
                        default=float(self._get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY)),
                    ): _number_selector(CONF_BATTERY_CAPACITY),
                    vol.Optional(
                        CONF_INVERTER_MAX_OUTPUT,
                        default=float(
                            self._get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT)
                        ),
                    ): _number_selector(CONF_INVERTER_MAX_OUTPUT),
                }
            ),
            {"collapsed": True},
        )

    def _immersion_section(self) -> object:
        """Return the immersion section: switch, water temperature sensor and element power.

        The target and minimum temperatures stay with the number entities, which persist
        them while the heater runs.
        """
        return section(
            vol.Schema(
                {
                    self._optional_key(CONF_IMMERSION_SWITCH): _entity_selector("switch"),
                    self._optional_key(CONF_IMMERSION_TEMP_SENSOR): _entity_selector(),
                    vol.Optional(
                        CONF_IMMERSION_WATTAGE,
                        default=float(self._get(CONF_IMMERSION_WATTAGE, DEFAULT_IMMERSION_WATTAGE)),
                    ): _number_selector(CONF_IMMERSION_WATTAGE),
                }
            ),
            {"collapsed": True},
        )

    def _ev_section(self) -> object:
        """Return the EV section: car efficiency."""
        return section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_CAR_EFFICIENCY_KWH_PER_100KM,
                        default=float(
                            self._get(
                                CONF_CAR_EFFICIENCY_KWH_PER_100KM,
                                DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
                            )
                        ),
                    ): _number_selector(CONF_CAR_EFFICIENCY_KWH_PER_100KM),
                }
            ),
            {"collapsed": True},
        )
