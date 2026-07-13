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

Options flow: edit tariff and thresholds without reinstalling.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BILL_START_DAY,
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
    DEFAULT_BILL_START_DAY,
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


def _rate_period_section(slot: dict) -> object:
    """Return a section() for one rate-period slot pre-filled from *slot*."""
    return section(
        vol.Schema(
            {
                vol.Optional("name", default=slot["name"]): selector.TextSelector(),
                vol.Optional("rate", default=slot["rate"]): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.001, unit_of_measurement="EUR/kWh"
                    )
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
        return await self.async_step_tariff()

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

        return await self.async_step_tariff()

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
                    "status": f"All sensors detected for {best_inverter.display_name}",
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

    async def async_step_tariff(self, user_input=None):
        """Step 2: Tariff configuration, with scheduling discovery summary."""
        errors: dict[str, str] = {}
        if user_input is not None:
            periods = _slots_to_rate_periods(user_input)
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

        schema = self._build_tariff_schema()
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
    def _build_tariff_schema(periods: list[dict] | None = None) -> vol.Schema:
        slots = _periods_to_slot_defaults(periods if periods is not None else DEFAULT_RATE_PERIODS)
        schema_dict: dict = {
            vol.Required(CONF_BASE_RATE, default=DEFAULT_BASE_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.001, unit_of_measurement="EUR/kWh"
                )
            ),
            vol.Optional(
                CONF_BASE_RATE_NAME, default=DEFAULT_BASE_RATE_NAME
            ): selector.TextSelector(),
            vol.Required(CONF_EXPORT_RATE, default=DEFAULT_EXPORT_RATE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.001, unit_of_measurement="EUR/kWh"
                )
            ),
            vol.Required(
                CONF_STANDING_CHARGE, default=DEFAULT_STANDING_CHARGE
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.001, unit_of_measurement="EUR/day"
                )
            ),
            vol.Required(CONF_PSO_LEVY, default=DEFAULT_PSO_LEVY): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=20, step=0.01, unit_of_measurement="EUR/month"
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
        for i, slot in enumerate(slots, 1):
            schema_dict[vol.Optional(f"rate_period_{i}")] = _rate_period_section(slot)
        return vol.Schema(schema_dict)

    async def async_step_forecast(self, user_input=None):
        """Step 3: Solar forecast integration (optional)."""
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
                vol.Optional(CONF_FORECAST_ENTITY_P10): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_FORECAST_ENTITY_D2): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_CARBON_INTENSITY_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_FORECAST_CONSERVATISM, default=DEFAULT_FORECAST_CONSERVATISM
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode="slider")
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
                    CONF_BATTERY_MIN_SOC,
                    default=DEFAULT_BATTERY_MIN_SOC,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=30, step=1, unit_of_measurement="%")
                ),
                vol.Optional(
                    CONF_CHEAP_RATE_FLOOR_SOC,
                    default=DEFAULT_CHEAP_RATE_FLOOR_SOC,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=80, step=5, unit_of_measurement="%")
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
            }
        )
        return self.async_show_form(step_id="battery", data_schema=schema)

    async def async_step_reconfigure(self, user_input=None):
        """Allow updating tariff settings without removing the integration.

        Shows the same form as the tariff setup step, pre-populated with the
        current entry values. On submit, updates entry data and reloads.
        Inverter entity mappings (set during initial auto-discovery) require a
        full remove-and-re-add to change.
        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            periods = _slots_to_rate_periods(user_input)
            updates = {
                CONF_RATE_PERIODS: periods,
                CONF_BASE_RATE: float(user_input[CONF_BASE_RATE]),
                CONF_BASE_RATE_NAME: str(
                    user_input.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
                ),
                CONF_EXPORT_RATE: float(user_input[CONF_EXPORT_RATE]),
                CONF_STANDING_CHARGE: float(user_input[CONF_STANDING_CHARGE]),
                CONF_PSO_LEVY: float(user_input[CONF_PSO_LEVY]),
                CONF_VAT_RATE: float(user_input[CONF_VAT_RATE]),
                CONF_DISCOUNT_RATE: float(user_input[CONF_DISCOUNT_RATE]),
                CONF_BILL_START_DAY: int(user_input[CONF_BILL_START_DAY]),
                CONF_CURRENCY: user_input.get(CONF_CURRENCY, DEFAULT_CURRENCY),
            }
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, **updates})
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        current_periods = (
            entry.options.get(CONF_RATE_PERIODS) or entry.data.get(CONF_RATE_PERIODS) or []
        )
        schema = self.__class__._build_tariff_schema(current_periods)
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GivEnergyOptionsFlow(config_entry)


class GivEnergyOptionsFlow(config_entries.OptionsFlow):
    """Options flow — tariff rates, per-period rates, thresholds, forecast."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    def _get(self, key, default):
        return self._config_entry.options.get(key) or self._config_entry.data.get(key) or default

    async def async_step_init(self, user_input=None):
        """Single-page options: tariff, per-period rates, thresholds, forecast."""
        errors: dict[str, str] = {}

        if user_input is not None:
            tariff = user_input.get("tariff_settings", {})
            thresholds = user_input.get("threshold_settings", {})
            forecast = user_input.get("forecast_settings", {})
            # Rate periods come from top-level rate_period_N sections
            self._options[CONF_RATE_PERIODS] = _slots_to_rate_periods(user_input)
            for key in [
                CONF_EXPORT_RATE,
                CONF_STANDING_CHARGE,
                CONF_PSO_LEVY,
                CONF_VAT_RATE,
                CONF_DISCOUNT_RATE,
            ]:
                self._options[key] = float(tariff[key])
            self._options[CONF_BILL_START_DAY] = int(tariff[CONF_BILL_START_DAY])
            self._options[CONF_BASE_RATE] = float(tariff[CONF_BASE_RATE])
            self._options[CONF_BASE_RATE_NAME] = str(
                tariff.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
            )
            self._options[CONF_CURRENCY] = tariff.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            self._options.update(thresholds)
            self._options.update({k: v for k, v in forecast.items() if v != ""})
            return self.async_create_entry(title="", data=self._options)

        current_periods = self._get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS)
        slots = _periods_to_slot_defaults(current_periods)

        schema_dict: dict = {
            vol.Required("tariff_settings"): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_BASE_RATE,
                            default=float(self._get(CONF_BASE_RATE, DEFAULT_BASE_RATE)),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=5, step=0.001, unit_of_measurement="EUR/kWh"
                            )
                        ),
                        vol.Optional(
                            CONF_BASE_RATE_NAME,
                            default=str(self._get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)),
                        ): selector.TextSelector(),
                        vol.Required(
                            CONF_EXPORT_RATE,
                            default=self._get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=1, step=0.001, unit_of_measurement="EUR/kWh"
                            )
                        ),
                        vol.Required(
                            CONF_STANDING_CHARGE,
                            default=self._get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=5, step=0.001, unit_of_measurement="EUR/day"
                            )
                        ),
                        vol.Required(
                            CONF_PSO_LEVY, default=self._get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=20, step=0.01, unit_of_measurement="EUR/month"
                            )
                        ),
                        vol.Required(
                            CONF_VAT_RATE, default=self._get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=30, step=0.1, unit_of_measurement="%"
                            )
                        ),
                        vol.Required(
                            CONF_DISCOUNT_RATE,
                            default=self._get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0, max=20, step=0.1, unit_of_measurement="%"
                            )
                        ),
                        vol.Required(
                            CONF_BILL_START_DAY,
                            default=self._get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(min=1, max=28, step=1)
                        ),
                        vol.Required(
                            CONF_CURRENCY, default=self._get(CONF_CURRENCY, DEFAULT_CURRENCY)
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=code, label=f"{code} ({symbol})"
                                    )
                                    for code, symbol in CURRENCIES.items()
                                ]
                            )
                        ),
                    }
                ),
                {"collapsed": False},
            ),
        }
        for i, slot in enumerate(slots, 1):
            schema_dict[vol.Optional(f"rate_period_{i}")] = _rate_period_section(slot)

        schema_dict[vol.Required("threshold_settings")] = section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_BATTERY_MIN_SOC,
                        default=self._get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5, max=30, step=1, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_CHEAP_RATE_FLOOR_SOC,
                        default=self._get(CONF_CHEAP_RATE_FLOOR_SOC, DEFAULT_CHEAP_RATE_FLOOR_SOC),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=80, step=5, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_OVERNIGHT_CHARGE_TARGET,
                        default=self._get(
                            CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=20, max=100, step=1, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_SKIP_CHARGE_SOC_THRESHOLD,
                        default=self._get(
                            CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=20, max=100, step=1, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_COST,
                        default=float(self._get(CONF_BATTERY_COST, DEFAULT_BATTERY_COST)),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=20000, step=100, unit_of_measurement="€"
                        )
                    ),
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
        schema_dict[vol.Required("forecast_settings")] = section(
            vol.Schema(
                {
                    vol.Optional(
                        CONF_FORECAST_PROVIDER, default=self._get(CONF_FORECAST_PROVIDER, "")
                    ): selector.SelectSelector(
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
                    vol.Optional(
                        CONF_FORECAST_ENTITY, default=self._get(CONF_FORECAST_ENTITY, "")
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                    vol.Optional(
                        CONF_FORECAST_ENTITY_P10, default=self._get(CONF_FORECAST_ENTITY_P10, "")
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                    vol.Optional(
                        CONF_FORECAST_ENTITY_D2, default=self._get(CONF_FORECAST_ENTITY_D2, "")
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                    vol.Optional(
                        CONF_CARBON_INTENSITY_ENTITY,
                        default=self._get(CONF_CARBON_INTENSITY_ENTITY, ""),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                    vol.Optional(
                        CONF_FORECAST_CONSERVATISM,
                        default=float(
                            self._get(CONF_FORECAST_CONSERVATISM, DEFAULT_FORECAST_CONSERVATISM)
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode="slider")
                    ),
                }
            ),
            {"collapsed": True},
        )

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_dict), errors=errors
        )
