"""
config_flow.py — Setup and options flow for GivEnergy Inverter Manager.

Setup wizard steps:
  1. inverter         — auto-discovers GivTCP entities. When fully detected,
                        shows only battery capacity and max output to confirm.
                        Falls back to manual entity entry if discovery fails.
  2. charge_scheduling — optional overnight charge scheduling (target SOC,
                         schedule switches, time slots). Auto-filled if found.
  3. tariff            — rate periods, export rate, standing charge, etc.
  4. forecast          — optional Forecast.Solar or Solcast integration.
  5. immersion         — optional immersion heater.
  6. ev                — optional EV charger.
  7. battery           — overnight charge thresholds.

Options flow: edit tariff and thresholds without reinstalling.
"""

from __future__ import annotations

from datetime import time
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BILL_START_DAY,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_EV_BATTERY_PROTECT_SOC,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
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
    CURRENCIES,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BILL_START_DAY,
    DEFAULT_CURRENCY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_EV_BATTERY_PROTECT_SOC,
    DEFAULT_EXPORT_RATE,
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
    DOMAIN,
    FORECAST_PROVIDER_FORECAST_SOLAR,
    FORECAST_PROVIDER_SOLCAST,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from .discovery import discover_ev_chargers, discover_givtcp_inverters

_MANUAL = "__manual__"

# Maps discover_givtcp_inverters() entity keys → config entry keys (CONF_* constants).
_DISCOVERY_TO_CONF: dict[str, str] = {
    "solar_power": CONF_SOLAR_POWER,
    "battery_soc": CONF_BATTERY_SOC,
    "battery_power": CONF_BATTERY_POWER,
    "grid_power": CONF_GRID_POWER,
    "house_load": CONF_HOUSE_LOAD,
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


def _validate_time(line_num: int, label: str, ts: str) -> None:
    t_parts = ts.split(":")
    if len(t_parts) != 2:
        raise ValueError(f"Line {line_num}: invalid {label} time {ts!r}") from None
    try:
        time(int(t_parts[0]), int(t_parts[1]))
    except ValueError:
        raise ValueError(f"Line {line_num}: invalid {label} time {ts!r}") from None


def _parse_rate_periods(raw: str) -> list[dict]:
    """Parse user-entered rate period text into a validated list of period dicts."""
    periods = []
    for line_num, line in enumerate(raw.strip().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Line {line_num}: expected 'Name, rate, HH:MM, HH:MM' — got {line!r}")
        name, rate_str, start_str, end_str = parts
        try:
            rate = float(rate_str)
        except ValueError:
            raise ValueError(f"Line {line_num}: invalid rate {rate_str!r}") from None
        _validate_time(line_num, "start", start_str)
        _validate_time(line_num, "end", end_str)
        periods.append({"name": name, "rate": rate, "start": start_str, "end": end_str})
    return periods


def _rate_periods_to_text(periods: list[dict]) -> str:
    return "\n".join(f"{p['name']}, {p['rate']}, {p['start']}, {p['end']}" for p in periods)


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

    def _build_inverter_options(self, best_inverter):
        options = [selector.SelectOptionDict(value=_MANUAL, label="Manual entry")]
        for inv in self._discovered_inverters:
            label = inv.display_name
            if not inv.is_fully_configured:
                label += " (some sensors missing)"
            options.append(selector.SelectOptionDict(value=inv.serial, label=label))
        default_inverter = best_inverter.serial if best_inverter else _MANUAL
        return options, default_inverter

    async def async_step_user(self, user_input=None):
        return await self.async_step_inverter(user_input)

    async def _handle_fully_configured_inverter(self, inverter, user_input):
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
        return await self.async_step_charge_scheduling()

    def _handle_partial_inverter(self, inverter, user_input):
        """Fill partial inverter discovery results."""
        for disc_key, conf_key in _DISCOVERY_TO_CONF.items():
            if disc_key in inverter.entities:
                user_input[conf_key] = inverter.entities[disc_key]

    async def _handle_manual_path(self, user_input):
        """Handle manual entity entry path."""
        required = [
            CONF_SOLAR_POWER,
            CONF_BATTERY_SOC,
            CONF_BATTERY_POWER,
            CONF_GRID_POWER,
            CONF_HOUSE_LOAD,
        ]
        if any(not user_input.get(k) for k in required):
            return {"base": "missing_entities"}
        self._data.update(user_input)
        serial = user_input.get("discovered_inverter", "manual")
        self._data[CONF_INVERTER_SERIAL] = serial
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        await self.async_step_charge_scheduling()
        return None

    def _build_auto_detected_schema(self, best_inverter, inverter_options):
        """Build schema for auto-detected inverter."""
        default_capacity = best_inverter.battery_capacity_kwh or DEFAULT_BATTERY_CAPACITY
        return vol.Schema(
            {
                vol.Optional(
                    "discovered_inverter", default=best_inverter.serial
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=inverter_options)),
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=default_capacity
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=100, step=0.1, unit_of_measurement="kWh"
                    )
                ),
                vol.Optional(
                    CONF_INVERTER_MAX_OUTPUT, default=DEFAULT_INVERTER_MAX_OUTPUT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=20, step=0.1, unit_of_measurement="kW")
                ),
            }
        )

    def _build_manual_schema(self, default_capacity, inverter_options):
        """Build schema for manual entity selection."""
        return vol.Schema(
            {
                vol.Optional(
                    "discovered_inverter", default=inverter_options[0][0]
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=inverter_options)),
                vol.Required(CONF_SOLAR_POWER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_BATTERY_SOC): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_BATTERY_POWER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_GRID_POWER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_HOUSE_LOAD): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=default_capacity
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=100, step=0.1, unit_of_measurement="kWh"
                    )
                ),
                vol.Optional(
                    CONF_INVERTER_MAX_OUTPUT, default=DEFAULT_INVERTER_MAX_OUTPUT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=20, step=0.1, unit_of_measurement="kW")
                ),
            }
        )

    async def async_step_inverter(self, user_input=None):
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

            errors = await self._handle_manual_path(user_input) or errors
            if not errors:
                return None

        # ── Build the form ────────────────────────────────────────────────────
        inverter_options, default_inverter = self._build_inverter_options(best_inverter)

        if is_auto_detected:
            schema = self._build_auto_detected_schema(best_inverter, inverter_options)
            return self.async_show_form(
                step_id="inverter",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "status": f"✓ All sensors detected for {best_inverter.display_name}",
                    "discovered_count": str(len(self._discovered_inverters)),
                },
            )

        default_capacity = (
            best_inverter.battery_capacity_kwh if best_inverter else None
        ) or DEFAULT_BATTERY_CAPACITY
        schema = self._build_manual_schema(default_capacity, inverter_options)
        return self.async_show_form(
            step_id="inverter",
            data_schema=schema,
            errors=errors,
            description_placeholders={"discovered_count": str(len(self._discovered_inverters))},
        )

    async def async_step_charge_scheduling(self, user_input=None):
        """
        Step 2: Charge scheduling confirmation (read-only summary, no entity selectors).

        The 5 GivTCP scheduling entities are already in self._data from discovery.
        This step just shows what was found — entity selector fields in config flow
        submissions cause HA to silently return 'unknown error' during schema
        validation regardless of approach, so we avoid them here entirely.
        The user can adjust entities post-setup via Settings > Integrations > Configure.
        """
        if user_input is not None:
            return await self.async_step_tariff()

        detected = sum(1 for k in _CHARGE_SCHEDULING_CONF_KEYS if self._data.get(k))

        if detected == 5:
            status = "All 5 scheduling entities detected — automatic overnight charging enabled"
        elif detected > 0:
            status = f"{detected}/5 scheduling entities detected — partial scheduling"
        else:
            status = "No scheduling entities detected — manual charging only"

        return self.async_show_form(
            step_id="charge_scheduling",
            data_schema=vol.Schema({}),
            description_placeholders={"status": status},
        )

    async def async_step_tariff(self, user_input=None):
        """Step 3: Tariff configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                periods = _parse_rate_periods(user_input.get("rate_periods_text", ""))
                self._data[CONF_RATE_PERIODS] = periods
                for key in [
                    CONF_EXPORT_RATE,
                    CONF_STANDING_CHARGE,
                    CONF_PSO_LEVY,
                    CONF_VAT_RATE,
                    CONF_DISCOUNT_RATE,
                ]:
                    self._data[key] = float(user_input[key])
                self._data[CONF_BILL_START_DAY] = int(user_input[CONF_BILL_START_DAY])
                self._data[CONF_BASE_RATE] = float(user_input[CONF_BASE_RATE])
                self._data[CONF_BASE_RATE_NAME] = str(
                    user_input.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
                )
                self._data[CONF_CURRENCY] = user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY)
                return await self.async_step_forecast()
            except ValueError as err:
                errors["rate_periods_text"] = str(err)

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_RATE, default=DEFAULT_BASE_RATE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.0001, unit_of_measurement="€/kWh"
                    )
                ),
                vol.Optional(
                    CONF_BASE_RATE_NAME, default=DEFAULT_BASE_RATE_NAME
                ): selector.TextSelector(),
                vol.Required(
                    "rate_periods_text", default=_rate_periods_to_text(DEFAULT_RATE_PERIODS)
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_EXPORT_RATE, default=DEFAULT_EXPORT_RATE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1, step=0.0001, unit_of_measurement="€/kWh"
                    )
                ),
                vol.Required(
                    CONF_STANDING_CHARGE, default=DEFAULT_STANDING_CHARGE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.0001, unit_of_measurement="€/day"
                    )
                ),
                vol.Required(CONF_PSO_LEVY, default=DEFAULT_PSO_LEVY): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20, step=0.01, unit_of_measurement="€/month"
                    )
                ),
                vol.Required(CONF_VAT_RATE, default=DEFAULT_VAT_RATE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=30, step=0.1, unit_of_measurement="%")
                ),
                vol.Required(
                    CONF_DISCOUNT_RATE, default=DEFAULT_DISCOUNT_RATE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="%")
                ),
                vol.Required(
                    CONF_BILL_START_DAY, default=DEFAULT_BILL_START_DAY
                ): selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=28, step=1)),
                vol.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=code, label=f"{code} ({symbol})")
                            for code, symbol in CURRENCIES.items()
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(step_id="tariff", data_schema=schema, errors=errors)

    async def async_step_forecast(self, user_input=None):
        """Step 4: Solar forecast integration (optional)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_immersion()
        schema = vol.Schema(
            {
                vol.Optional(CONF_FORECAST_PROVIDER): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=FORECAST_PROVIDER_FORECAST_SOLAR, label="Forecast.Solar"
                            ),
                            selector.SelectOptionDict(
                                value=FORECAST_PROVIDER_SOLCAST, label="Solcast"
                            ),
                        ]
                    )
                ),
                vol.Optional(CONF_FORECAST_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )
        return self.async_show_form(step_id="forecast", data_schema=schema)

    async def async_step_immersion(self, user_input=None):
        """Step 5: Immersion heater (optional)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_ev()
        schema = vol.Schema(
            {
                vol.Optional(CONF_IMMERSION_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    CONF_IMMERSION_WATTAGE, default=DEFAULT_IMMERSION_WATTAGE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500, max=6000, step=100, unit_of_measurement="W"
                    )
                ),
                vol.Optional(CONF_IMMERSION_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_IMMERSION_TARGET_TEMP, default=DEFAULT_IMMERSION_TARGET_TEMP
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=40, max=75, step=1, unit_of_measurement="°C")
                ),
                vol.Optional(
                    CONF_IMMERSION_MIN_TEMP, default=DEFAULT_IMMERSION_MIN_TEMP
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
                ),
            }
        )
        return self.async_show_form(step_id="immersion", data_schema=schema)

    async def async_step_ev(self, user_input=None):
        """Step 6: EV charger (optional). Auto-discovers Zappi, Wallbox, OCPP, Ohme, Easee."""
        errors: dict[str, str] = {}
        all_states = {s.entity_id: s for s in self.hass.states.async_all()}
        self._discovered_chargers = discover_ev_chargers(all_states)

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery()

        manual_ev = "__manual_ev__"
        charger_options = [selector.SelectOptionDict(value=manual_ev, label="None / Manual entry")]
        for ch in self._discovered_chargers:
            charger_options.append(
                selector.SelectOptionDict(value=ch.serial, label=ch.display_name)
            )
        default_charger = (
            self._discovered_chargers[0].serial
            if len(self._discovered_chargers) == 1
            else manual_ev
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    "discovered_charger", default=default_charger
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=charger_options)),
            }
        )
        return self.async_show_form(
            step_id="ev",
            data_schema=schema,
            errors=errors,
            description_placeholders={"discovered_count": str(len(self._discovered_chargers))},
        )

    async def async_step_battery(self, user_input=None):
        """Step 7: Battery management thresholds."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="GivEnergy Inverter Manager", data=self._data)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BATTERY_MIN_SOC, default=DEFAULT_BATTERY_MIN_SOC
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=30, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_OVERNIGHT_CHARGE_TARGET, default=DEFAULT_OVERNIGHT_CHARGE_TARGET
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=100, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_SKIP_CHARGE_SOC_THRESHOLD, default=DEFAULT_SKIP_CHARGE_SOC_THRESHOLD
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=100, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_SURPLUS_DIVERT_SOC, default=SURPLUS_DIVERT_SOC_THRESHOLD
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=50, max=100, step=5, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_SURPLUS_DIVERT_MIN_W, default=SURPLUS_DIVERT_MIN_POWER_W
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=2000, step=100, unit_of_measurement="W"
                    )
                ),
                vol.Optional(
                    CONF_EV_BATTERY_PROTECT_SOC, default=DEFAULT_EV_BATTERY_PROTECT_SOC
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=50, step=5, unit_of_measurement="%")
                ),
            }
        )
        return self.async_show_form(step_id="battery", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GivEnergyOptionsFlow(config_entry)


class GivEnergyOptionsFlow(config_entries.OptionsFlow):
    """Options flow — edit tariff and thresholds after initial setup."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    def _get(self, key, default):
        return self._config_entry.options.get(key) or self._config_entry.data.get(key) or default

    async def async_step_init(self, user_input=None):
        return await self.async_step_tariff(user_input)

    async def async_step_tariff(self, user_input=None):
        errors: dict[str, str] = {}
        current_periods = self._get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS)

        if user_input is not None:
            try:
                periods = _parse_rate_periods(user_input.get("rate_periods_text", ""))
                self._options[CONF_RATE_PERIODS] = periods
                for key in [
                    CONF_EXPORT_RATE,
                    CONF_STANDING_CHARGE,
                    CONF_PSO_LEVY,
                    CONF_VAT_RATE,
                    CONF_DISCOUNT_RATE,
                ]:
                    self._options[key] = float(user_input[key])
                self._options[CONF_BILL_START_DAY] = int(user_input[CONF_BILL_START_DAY])
                self._options[CONF_BASE_RATE] = float(user_input[CONF_BASE_RATE])
                self._options[CONF_BASE_RATE_NAME] = str(
                    user_input.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
                )
                return await self.async_step_thresholds()
            except ValueError as err:
                errors["rate_periods_text"] = str(err)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BASE_RATE, default=float(self._get(CONF_BASE_RATE, DEFAULT_BASE_RATE))
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.0001, unit_of_measurement="€/kWh"
                    )
                ),
                vol.Optional(
                    CONF_BASE_RATE_NAME,
                    default=str(self._get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)),
                ): selector.TextSelector(),
                vol.Required(
                    "rate_periods_text", default=_rate_periods_to_text(current_periods)
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_EXPORT_RATE, default=self._get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1, step=0.0001, unit_of_measurement="€/kWh"
                    )
                ),
                vol.Required(
                    CONF_STANDING_CHARGE,
                    default=self._get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.0001, unit_of_measurement="€/day"
                    )
                ),
                vol.Required(
                    CONF_PSO_LEVY, default=self._get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20, step=0.01, unit_of_measurement="€/month"
                    )
                ),
                vol.Required(
                    CONF_VAT_RATE, default=self._get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=30, step=0.1, unit_of_measurement="%")
                ),
                vol.Required(
                    CONF_DISCOUNT_RATE, default=self._get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=20, step=0.1, unit_of_measurement="%")
                ),
                vol.Required(
                    CONF_BILL_START_DAY,
                    default=self._get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY),
                ): selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=28, step=1)),
            }
        )
        return self.async_show_form(step_id="tariff", data_schema=schema, errors=errors)

    async def async_step_thresholds(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BATTERY_MIN_SOC,
                    default=self._get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=30, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_OVERNIGHT_CHARGE_TARGET,
                    default=self._get(
                        CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=100, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_SKIP_CHARGE_SOC_THRESHOLD,
                    default=self._get(
                        CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=100, step=1, unit_of_measurement="%")
                ),
            }
        )
        return self.async_show_form(step_id="thresholds", data_schema=schema)
