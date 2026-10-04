"""
dashboard.py — Lovelace dashboard YAML generator for GivEnergy Inverter Manager.

Provides a single HA service: givenergy_inverter_manager.get_dashboard_yaml

Calling this service from Developer Tools → Actions returns complete, ready-to-paste
Lovelace YAML pre-filled with your actual entity IDs. No find-and-replace needed.

The generated dashboard has four views:
  1. Power Flow   — live animated energy flow (requires power-flow-card-plus from HACS)
  2. Today        — daily energy totals, cost breakdown, self-sufficiency
  3. Battery      — battery health, charge decision, night survival
  4. Controls     — charge target slider, switches, EV charger state

How to use:
  1. Developer Tools → Actions → givenergy_inverter_manager.get_dashboard_yaml
  2. Click Perform Action
  3. Copy the YAML from the response
  4. Settings → Dashboards → New dashboard (Blank)
  5. Three-dot menu → Edit dashboard → Raw configuration editor
  6. Paste, save

Power flow view requires power-flow-card-plus from HACS:
  https://github.com/flixlix/power-flow-card-plus

All other views use only built-in HA Lovelace cards — no other dependencies.
"""

from __future__ import annotations

import os
from dataclasses import replace

import yaml
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import CONF_IMMERSION_TEMP_SENSOR, DOMAIN
from .core.rules import suggest_appliance_run
from .core.tariff import BillBreakdown, TariffConfig, build_tariff
from .logging import get_logger

_LOG = get_logger(__name__)

SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"
SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"
SERVICE_COMPARE_TARIFF = "compare_tariff"
SERVICE_YEAR_ON_YEAR = "year_on_year_summary"
SERVICE_EXPORT_ENERGY_DATA = "export_energy_data"
SERVICE_GET_ROI_SUMMARY = "get_roi_summary"


def loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the config entries of this integration that are currently loaded."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def require_loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the loaded entries, or raise when none is loaded."""
    if not (entries := loaded_entries(hass)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_config_entry",
        )
    return entries


def _entity_id(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> str:
    """Look up the current entity_id for one of our entities by its unique_id suffix."""
    reg = er.async_get(hass)
    uid = f"{entry_id}_{unique_id_suffix}"
    entry = (
        reg.async_get_entity_id("sensor", DOMAIN, uid)
        or reg.async_get_entity_id("switch", DOMAIN, uid)
        or reg.async_get_entity_id("number", DOMAIN, uid)
    )
    # Fall back to a predictable name if not registered yet
    return entry or f"sensor.givenergy_inverter_manager_{unique_id_suffix}"


_EV_CHARGER_CANDIDATES = [
    "sensor.myenergi_zappi_power_ct_internal_load",
    "sensor.myenergi_zappi_power_ct_internal_load_2",
    "sensor.myenergi_zappi2_power_ct_internal_load",
    "sensor.wallbox_charging_power",
    "sensor.ohme_current_power",
]


def _find_ev_charger_power(hass: HomeAssistant, integration_ev_power: str) -> str:
    """Return the best available EV charger power entity.

    Checks known external EV charger integrations first since these report power
    directly. Falls back to the integration's own sensor if none are found.
    """
    for candidate in _EV_CHARGER_CANDIDATES:
        if hass.states.get(candidate) is not None:
            return candidate
    return integration_ev_power


class _DashboardDumper(yaml.SafeDumper):
    """SafeDumper that writes multi-line strings as literal blocks and never folds."""

    def ignore_aliases(self, data):
        return True


def _represent_str(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_DashboardDumper.add_representer(str, _represent_str)


def _dump_yaml(data: dict) -> str:
    """Serialise with the options Home Assistant uses for its own YAML output."""
    return yaml.dump(
        data,
        Dumper=_DashboardDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=10_000,
    )


def _apex_config() -> dict:
    return {
        "chart": {"height": 150, "zoom": {"enabled": False}},
        "tooltip": {"shared": True, "followCursor": True},
        "stroke": {"curve": "smooth", "width": 2},
        "markers": {"size": 0, "hover": {"size": 5}},
        "legend": {"show": False},
    }


def _build_immersion_section(
    immersion_temp_sensor: str,
    immersion_reason: str,
    num_target: str,
    num_min: str,
    immersion_today: str,
) -> dict | None:
    """Build the immersion block for the power flow view.

    A vertical-stack of a 12 hour temperature chart (water, target, minimum),
    a tile with the divert reason and a 12 hour chart of immersion energy today.
    Returns None when no immersion temperature sensor is configured.
    Requires apexcharts-card from HACS.
    """
    if not immersion_temp_sensor:
        return None

    def series(entity: str, name: str, color: str, width: int) -> dict:
        return {"entity": entity, "name": name, "color": color, "stroke_width": width}

    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "custom:apexcharts-card",
                "header": {"show": True, "title": "Immersion Temperature (12h)"},
                "graph_span": "12h",
                "apex_config": _apex_config(),
                "series": [
                    series(immersion_temp_sensor, "Water", "#03a9f4", 2),
                    series(num_target, "Target", "#f44336", 1),
                    series(num_min, "Minimum", "#ff9800", 1),
                ],
            },
            {
                "type": "tile",
                "entity": immersion_reason,
                "name": " ",
                "show_entity_picture": False,
                "hide_state": False,
                "vertical": False,
                "features_position": "bottom",
            },
            {
                "type": "custom:apexcharts-card",
                "header": {"show": True, "title": "Power"},
                "graph_span": "12h",
                "yaxis": [{"min": 0}],
                "apex_config": _apex_config(),
                "series": [series(immersion_today, "Immersion Power Today", "#03a9f4", 2)],
            },
        ],
    }


_DASHBOARD_HEADER = f"""\
# GivEnergy Inverter Manager — Generated Dashboard
# Generated by: Developer Tools → Actions → {DOMAIN}.{SERVICE_GET_DASHBOARD_YAML}
#
# View 1 (Power Flow) requires power-flow-card-plus from HACS:
#   https://github.com/flixlix/power-flow-card-plus
# Immersion section requires apexcharts-card from HACS:
#   https://github.com/RomRider/apexcharts-card
# All other views use only built-in HA cards.
#
# To use: Settings → Dashboards → new blank dashboard
#         Three-dot menu → Edit dashboard → Raw configuration editor → paste

"""


def _build_dashboard_yaml(hass: HomeAssistant, entry_id: str) -> str:
    """Return the dashboard as YAML text, with a short header comment."""
    return _DASHBOARD_HEADER + _dump_yaml(_build_dashboard(hass, entry_id))


def _build_dashboard(hass: HomeAssistant, entry_id: str) -> dict:
    """
    Build the Lovelace configuration for all four views as a dict.

    Uses actual entity IDs from the entity registry so names customised
    in the HA UI are automatically respected.
    """

    def e(suffix: str) -> str:
        return _entity_id(hass, entry_id, suffix)

    # ── sensor entity IDs ────────────────────────────────────────────────────
    solar_power = e("solar_power")
    battery_soc = e("battery_soc")
    grid_power = e("grid_power")
    house_load = e("house_load")
    battery_power = e("battery_power")
    immersion_power = e("immersion_power")
    current_rate = e("current_rate")
    solar_today = e("solar_today")
    import_today = e("import_today")
    export_today = e("export_today")
    zappi_today = e("zappi_today")
    immersion_today = e("immersion_today")
    import_cost_today = e("import_cost_today")
    export_earnings = e("export_earnings_today")
    zappi_cost_today = e("zappi_cost_today")
    immersion_cost_today = e("immersion_cost_today")
    house_cost_today = e("house_cost_today")
    house_kwh_today = e("house_kwh_today")
    self_sufficiency = e("self_sufficiency")
    self_consumption = e("self_consumption")
    accrued_bill = e("accrued_bill")
    projected_bill = e("projected_bill")
    days_remaining = e("days_remaining_in_period")
    battery_cycles = e("battery_cycles")
    battery_life = e("battery_remaining_life")
    days_since_full = e("days_since_full_charge")
    charge_target = e("overnight_charge_target")
    charge_reason = e("overnight_charge_reason")
    charge_cost = e("overnight_charge_cost")
    immersion_reason = e("immersion_divert_reason")
    soc_at_sunrise = e("estimated_soc_at_sunrise")
    survival_reason = e("night_survival_reason")
    is_clipping = e("is_clipping")
    current_rate_period = e("current_rate_period")
    live_grid_cost_rate = e("live_grid_cost_rate")
    cheap_rate_floor = e("cheap_rate_floor_status")
    immersion_savings = e("immersion_savings_today")
    solar_forecast_today = e("solar_forecast_kwh_today")
    solar_vs_forecast_pct = e("solar_actual_vs_forecast_pct")
    forecast_accuracy_yesterday = e("yesterday_forecast_accuracy_pct")
    ev_state = e("ev_charger_state")
    ev_power = _find_ev_charger_power(hass, e("ev_power"))
    ev_session = e("ev_session_energy")
    ev_draining = e("ev_draining_battery")
    ev_protection_reason = e("ev_protection_reason")
    ev_charging_source = e("ev_charging_source")
    ev_solar_surplus = e("ev_solar_surplus_available")
    inverter_temp = e("inverter_temperature")
    inverter_temp_status = e("inverter_temperature_status")
    dry_run_active = e("dry_run_active")
    dry_run_skipped = e("dry_run_last_skipped")
    sw_enable_charge_target = e("charge_target_override_enabled")
    sw_auto_immersion = e("auto_immersion")
    sw_immersion_mgd = e("immersion_managed")
    sw_skip_charge = e("skip_charge_override")
    num_charge_target = e("charge_target_override")
    num_immersion_target = e("immersion_target_temp")
    num_immersion_min = e("immersion_min_temp")
    num_immersion_gap = e("immersion_hysteresis")

    entry_cfg = _entry_config(hass, entry_id)
    immersion_section = _build_immersion_section(
        entry_cfg.get(CONF_IMMERSION_TEMP_SENSOR, ""),
        immersion_reason,
        num_immersion_target,
        num_immersion_min,
        immersion_today,
    )

    def row(entity: str, name: str, **extra) -> dict:
        return {"entity": entity, "name": name, **extra}

    power_flow_cards = [
        {
            "type": "custom:power-flow-card-plus",
            "entities": {
                "solar": {
                    "entity": solar_power,
                    "color_icon": False,
                    "color_value": False,
                    "invert_state": False,
                    "secondary_info_entity": is_clipping,
                    "secondary_info": {
                        "template": (
                            f'{{{{- "·⚡Clip" if states("{is_clipping}") == "clipping" else "" }}}}'
                        )
                    },
                },
                "battery": {
                    "entity": battery_power,
                    "state_of_charge": battery_soc,
                    "show_state_of_charge": True,
                },
                "grid": {
                    "entity": grid_power,
                    "use_metadata": False,
                    "invert_state": False,
                    "display_state": "one_way",
                    "secondary_info": {
                        "entity": live_grid_cost_rate,
                        "icon": "mdi:cash-clock",
                        "decimals": 4,
                        "display_zero": True,
                        "color_value": False,
                        "unit_of_measurement": " ",
                    },
                },
                "home": {
                    "entity": house_load,
                    "subtract_individual": False,
                    "hide": False,
                },
                "individual": [
                    {
                        "entity": ev_power,
                        "name": "Car Charger",
                        "icon": "mdi:car-electric",
                        "display_zero": False,
                        "color": "#4CAF50",
                    },
                    {
                        "entity": immersion_power,
                        "name": "Immersion",
                        "icon": "mdi:water-boiler",
                        "display_zero": False,
                        "color": "#FF9800",
                    },
                ],
            },
            "title": "Live Power Flow",
            "min_flow_rate": 0.75,
            "max_flow_rate": 6,
            "display_zero_lines": {
                "mode": "transparency",
                "transparency": 75,
                "grey_color": [189, 189, 189],
            },
            "allow_layout_break": False,
            "kilo_threshold": 1000,
            "base_decimals": 0,
            "kilo_decimals": 1,
            "disable_dots": False,
            "clickable_entities": True,
            "no_labels": False,
        },
        {
            "show_name": True,
            "show_icon": True,
            "show_state": True,
            "type": "glance",
            "title": "Energy Today",
            "columns": 5,
            "entities": [
                row(solar_today, "Generated"),
                row(import_today, "Imported"),
                row(export_today, "Exported"),
                row(house_kwh_today, "Used"),
                row(immersion_today, "Immersion"),
            ],
        },
    ]
    if immersion_section is not None:
        power_flow_cards.append(immersion_section)

    today_cards = [
        {
            "show_name": True,
            "show_icon": True,
            "show_state": True,
            "type": "glance",
            "title": "Energy Today",
            "entities": [
                row(solar_today, "Generated"),
                row(import_today, "Import"),
                row(export_today, "Export"),
                row(zappi_today, "EV"),
                row(immersion_today, "Immersion"),
            ],
        },
        {
            "type": "entities",
            "entities": [
                row(current_rate, "Current Rate"),
                row(current_rate_period, "Rate Period"),
                {"type": "divider"},
                row(import_cost_today, "Import Cost"),
                row(export_earnings, "Export Earnings"),
                row(zappi_cost_today, "EV Charging Cost"),
                row(immersion_cost_today, "Immersion Cost"),
                row(immersion_savings, "Immersion Savings"),
                row(house_cost_today, "Rest-of-House Cost"),
            ],
            "title": "Cost Breakdown",
        },
        {
            "type": "history-graph",
            "title": "Cost build — today",
            "hours_to_show": 24,
            "entities": [
                row(import_cost_today, "Grid Import"),
                row(house_cost_today, "Rest of House"),
                row(zappi_cost_today, "EV Charging"),
                row(immersion_cost_today, "Immersion"),
                row(export_earnings, "Export Earnings"),
            ],
        },
        {
            "type": "history-graph",
            "title": "Solar generation — today",
            "hours_to_show": 24,
            "entities": [row(solar_today, "Actual")],
        },
        {
            "type": "entities",
            "title": "Solar vs Forecast",
            "entities": [
                row(solar_today, "Generated today"),
                row(solar_forecast_today, "Today's forecast"),
                row(solar_vs_forecast_pct, "Tracking", icon="mdi:chart-line"),
                row(forecast_accuracy_yesterday, "Yesterday's accuracy"),
            ],
        },
        {
            "square": False,
            "type": "grid",
            "columns": 2,
            "cards": [
                {
                    "type": "gauge",
                    "entity": self_sufficiency,
                    "name": "Self-Sufficiency",
                    "min": 0,
                    "max": 100,
                    "severity": {"green": 60, "yellow": 30, "red": 0},
                },
                {
                    "type": "gauge",
                    "entity": self_consumption,
                    "name": "Self-Consumption",
                    "min": 0,
                    "max": 100,
                    "severity": {"green": 70, "yellow": 40, "red": 0},
                },
            ],
            "title": "Self Sufficiency",
        },
        {
            "type": "entities",
            "entities": [
                row(accrued_bill, "Accrued This Period"),
                row(projected_bill, "Projected Total"),
                row(days_remaining, "Days Remaining"),
            ],
            "title": "Bill Prediction",
            "show_header_toggle": False,
            "state_color": False,
        },
    ]

    battery_cards = [
        {
            "type": "gauge",
            "entity": battery_soc,
            "name": "Battery SoC",
            "min": 0,
            "max": 100,
            "needle": True,
            "severity": {"green": 50, "yellow": 20, "red": 0},
        },
        {
            "type": "history-graph",
            "title": "Battery SoC — 24h",
            "hours_to_show": 24,
            "entities": [row(battery_soc, "SoC"), row(battery_power, "Power (W)")],
        },
        {
            "type": "entities",
            "entities": [
                row(battery_power, "Charge / Discharge Power"),
                row(charge_target, "Recommended Target Tonight"),
                row(charge_reason, "Reason", icon="mdi:information-outline"),
                row(charge_cost, "Estimated Charge Cost"),
                row(soc_at_sunrise, "Estimated SoC at Sunrise"),
                row(survival_reason, "Night Survival Status", icon="mdi:moon-waning-crescent"),
                row(cheap_rate_floor, "Cheap Rate Floor", icon="mdi:floor-plan"),
            ],
            "title": "Tonight's Charge Plan",
        },
        {
            "type": "entities",
            "entities": [
                row(battery_cycles, "Total Cycles"),
                row(battery_life, "Estimated Life Remaining"),
                row(days_since_full, "Days Since Full Charge"),
                row(inverter_temp, "Inverter Temperature"),
                row(inverter_temp_status, "Inverter Status", icon="mdi:thermometer-alert"),
            ],
            "title": "Battery Health",
        },
    ]

    dry_run_condition = [{"condition": "state", "entity": dry_run_active, "state": "True"}]
    controls_cards = [
        {
            "type": "conditional",
            "conditions": dry_run_condition,
            "card": {
                "type": "markdown",
                "content": (
                    "## ⚠️ Dry Run Mode Active\n"
                    "\n"
                    "This integration is in **simulation mode**. All sensor values update "
                    "normally and charge decisions are calculated, but **no commands are "
                    "sent to your inverter or EV charger**.\n"
                    "\n"
                    "To go live, disable Dry Run in Settings → Integrations → GivEnergy "
                    "Inverter Manager → Configure."
                ),
            },
        },
        {
            "type": "conditional",
            "conditions": dry_run_condition,
            "card": {
                "type": "entities",
                "title": "Dry Run Status",
                "entities": [
                    row(dry_run_active, "Dry Run Mode", icon="mdi:test-tube"),
                    row(
                        dry_run_skipped,
                        "Last Skipped Action",
                        icon="mdi:skip-next-circle-outline",
                    ),
                ],
            },
        },
        {
            "type": "entities",
            "entities": [
                row(sw_enable_charge_target, "Enable Charge Target Override"),
                row(num_charge_target, "Overnight Charge Target"),
                row(sw_skip_charge, "Force Skip Charge Tonight"),
            ],
            "title": "Overnight Charging",
        },
        {
            "type": "entities",
            "entities": [
                row(sw_auto_immersion, "Auto Immersion Divert"),
                row(sw_immersion_mgd, "Immersion Heater (Managed)"),
                row(immersion_reason, "Divert Reason", icon="mdi:water-boiler"),
                {"type": "divider"},
                row(num_immersion_target, "Target Temperature"),
                row(num_immersion_min, "Minimum Temperature"),
                row(num_immersion_gap, "Restart Gap"),
            ],
            "title": "Immersion Heater",
        },
        {
            "type": "entities",
            "entities": [
                row(ev_state, "Charger State", icon="mdi:ev-station"),
                row(ev_power, "Charge Power", icon="mdi:lightning-bolt"),
                row(ev_session, "Session Energy"),
                row(ev_draining, "Draining Battery"),
                row(ev_protection_reason, "Mode Decision", icon="mdi:car-electric"),
                row(ev_charging_source, "Charging Source"),
                row(ev_solar_surplus, "Solar Surplus Available"),
            ],
            "title": "EV Charger",
        },
    ]

    return {
        "views": [
            {
                "title": "Power Flow",
                "icon": "mdi:solar-power-variant",
                "path": "power-flow",
                "cards": power_flow_cards,
            },
            {"title": "Today", "icon": "mdi:calendar-today", "path": "today", "cards": today_cards},
            {
                "title": "Battery",
                "icon": "mdi:battery-charging",
                "path": "battery",
                "cards": battery_cards,
            },
            {"title": "Controls", "icon": "mdi:tune", "path": "controls", "cards": controls_cards},
        ]
    }


def _entry_config(hass: HomeAssistant, entry_id: str) -> dict:
    """Return the config entry's data with options layered over it."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            return {**entry.data, **entry.options}
    return {}


def _make_roi_summary_handler(hass: HomeAssistant):
    """Return the get_roi_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Return ROI metrics for today/week/month/year and battery health."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {}
        d = coordinator.data
        self_consumed_kwh = max(0.0, d.today.solar_kwh - d.today.export_kwh)
        avg_import_rate = (
            d.today.total_import_cost / d.today.import_kwh
            if d.today.import_kwh > 0
            else d.current_rate
        )
        export_rate = (
            d.today.export_earnings / d.today.export_kwh if d.today.export_kwh > 0 else 0.0
        )
        self_consumption_saving = self_consumed_kwh * max(0.0, avg_import_rate - export_rate)
        return {
            "today": {
                "solar_kwh": round(d.today.solar_kwh, 3),
                "export_kwh": round(d.today.export_kwh, 3),
                "import_kwh": round(d.today.import_kwh, 3),
                "self_consumed_kwh": round(self_consumed_kwh, 3),
                "self_consumption_saving": round(self_consumption_saving, 4),
                "import_cost": round(d.today.total_import_cost, 4),
                "export_earnings": round(d.today.export_earnings, 4),
                "net_position": round(d.today.net_position, 4),
                "battery_throughput_kwh": round(d.today.battery_throughput_kwh, 3),
                "self_sufficiency_pct": round(d.today.self_sufficiency_pct, 1),
            },
            "week": {
                "solar_kwh": round(d.week.solar_kwh, 3),
                "export_kwh": round(d.week.export_kwh, 3),
                "import_kwh": round(d.week.import_kwh, 3),
                "import_cost": round(d.week.total_import_cost, 4),
                "export_earnings": round(d.week.export_earnings, 4),
                "net_position": round(d.week.net_position, 4),
            },
            "month": {
                "solar_kwh": round(d.month.solar_kwh, 3),
                "export_kwh": round(d.month.export_kwh, 3),
                "import_kwh": round(d.month.import_kwh, 3),
                "import_cost": round(d.month.total_import_cost, 4),
                "export_earnings": round(d.month.export_earnings, 4),
                "net_position": round(d.month.net_position, 4),
            },
            "year": {
                "solar_kwh": round(d.year.solar_kwh, 3),
                "export_kwh": round(d.year.export_kwh, 3),
                "import_kwh": round(d.year.import_kwh, 3),
                "export_earnings": round(d.year.export_earnings, 4),
            },
            "battery": {
                "total_cycles": round(d.battery_stats.total_cycles, 2),
                "remaining_life_pct": round(d.battery_stats.estimated_remaining_life_pct, 1),
                "throughput_today_kwh": round(d.today.battery_throughput_kwh, 3),
            },
        }

    return handle


def _bill_side(bill: BillBreakdown, tariff: TariffConfig) -> dict:
    """Return one side of a tariff comparison from a bill breakdown."""
    import_cost = (bill.energy - bill.supplier_saving) * (1 + tariff.vat_rate / 100)
    before_export = bill.before_vat + bill.vat
    return {
        "import_cost": round(import_cost, 4),
        "standing_charges": round(before_export - import_cost, 4),
        "export_earnings": round(bill.export_credit, 4),
        "net_cost": round(bill.total, 4),
        "discount_rate": tariff.discount_rate,
        "vat_rate": tariff.vat_rate,
        "bill": {
            "energy": bill.energy,
            "supplier_saving": bill.supplier_saving,
            "standing_charge": bill.standing_charge,
            "pso_levy": bill.pso_levy,
            "vat": bill.vat,
            "export_credit": bill.export_credit,
            "total": bill.total,
        },
    }


def _compare_tariff_for_entry(coordinator, data) -> dict:
    """Compare one entry's bill period so far with a flat-rate alternative.

    Both sides go through TariffConfig.calculate_bill, so energy, supplier saving,
    standing charge, PSO levy, VAT and export credit are worked out the same way.
    """
    d = coordinator.data
    tariff = build_tariff(coordinator._effective_cfg())
    alt_rate = float(data["rate"])
    alt_standing = float(data.get("standing_charge", 0.0))
    alt_export_rate = float(data.get("export_rate", 0.0))
    overrides = {
        "standing_charge": alt_standing,
        "export_rate": alt_export_rate,
    }
    for field_name in ("discount_rate", "vat_rate", "pso_levy"):
        if data.get(field_name) is not None:
            overrides[field_name] = float(data[field_name])
    alt_tariff = replace(tariff, **overrides)

    days = d.days_in_period
    period_days = days + d.days_remaining
    import_kwh = d.month.import_kwh
    export_kwh = d.month.export_kwh

    current_bill = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(d.month.total_import_cost),
        days,
        period_days,
        d.month.export_earnings,
    )
    alt_bill = alt_tariff.calculate_bill(
        import_kwh * alt_rate, days, period_days, export_kwh * alt_export_rate
    )
    current = _bill_side(current_bill, tariff)
    alternative = _bill_side(alt_bill, alt_tariff)
    alternative.update(
        {
            "rate": alt_rate,
            "standing_charge_per_day": alt_standing,
            "export_rate": alt_export_rate,
            "pso_levy_per_period": alt_tariff.pso_levy,
        }
    )
    current["pso_levy_per_period"] = tariff.pso_levy
    return {
        "period_days": days,
        "period_length_days": period_days,
        "import_kwh": round(import_kwh, 3),
        "export_kwh": round(export_kwh, 3),
        "current_tariff": current,
        "comparison_tariff": alternative,
        "saving": round(current_bill.total - alt_bill.total, 4),
    }


def _make_compare_tariff_handler(hass: HomeAssistant):
    """Return the compare_tariff service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare the current bill period against a flat-rate alternative tariff.

        Service data fields:
          rate            - flat import rate of the comparison tariff (EUR/kWh, required)
          standing_charge - daily standing charge of the comparison tariff (EUR/day, default 0)
          export_rate     - export rate of the comparison tariff (EUR/kWh, default 0)
          discount_rate   - supplier discount in percent (default: the configured tariff's)
          vat_rate        - VAT in percent (default: the configured tariff's)
          pso_levy        - PSO levy per bill period (default: the configured tariff's)

        The top level of the response describes the first loaded entry. With more than
        one entry set up, "entries" lists every entry's comparison.
        """
        results = []
        for entry in require_loaded_entries(hass):
            coordinator = entry.runtime_data
            if coordinator.data is None:
                continue
            result = _compare_tariff_for_entry(coordinator, call.data)
            result["entry_id"] = entry.entry_id
            result["title"] = entry.title
            results.append(result)
        if not results:
            return {}
        return {**results[0], "entries": results}

    return handle


def _make_year_on_year_handler(hass: HomeAssistant):
    """Return the year_on_year_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare current billing month against the same month one year ago."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {}

        d = coordinator.data
        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        n_snapshots = len(snapshots)

        current = {
            "solar_kwh": round(d.month.solar_kwh, 3),
            "import_kwh": round(d.month.import_kwh, 3),
            "export_kwh": round(d.month.export_kwh, 3),
            "import_cost": round(d.month.total_import_cost, 4),
            "export_earnings": round(d.month.export_earnings, 4),
            "self_sufficiency_pct": round(d.month.self_sufficiency_pct, 1),
        }

        if n_snapshots < 12:
            return {
                "snapshots_available": n_snapshots,
                "snapshots_needed": 12,
                "no_data": True,
                "message": (
                    f"Year-on-year comparison requires 12 completed billing months. "
                    f"{n_snapshots} available. "
                    f"Full comparison will be ready in {12 - n_snapshots} more billing cycles."
                ),
                "current_month": current,
            }

        last_year = snapshots[-12]

        def _delta(key: str) -> float:
            curr_val = current.get(key, 0.0) or 0.0
            prev_val = float(last_year.get(key, 0.0) or 0.0)
            return round(curr_val - prev_val, 4)

        def _delta_pct(key: str) -> float | None:
            prev_val = float(last_year.get(key, 0.0) or 0.0)
            if prev_val == 0:
                return None
            return round((current.get(key, 0.0) - prev_val) / prev_val * 100, 1)

        return {
            "snapshots_available": n_snapshots,
            "no_data": False,
            "current_month": current,
            "last_year_same_month": {
                "solar_kwh": round(float(last_year.get("solar_kwh", 0.0)), 3),
                "import_kwh": round(float(last_year.get("import_kwh", 0.0)), 3),
                "export_kwh": round(float(last_year.get("export_kwh", 0.0)), 3),
                "import_cost": round(
                    sum(last_year.get("import_cost_by_period", {}).values()), 4
                ),
                "export_earnings": round(float(last_year.get("export_earnings", 0.0)), 4),
                "self_sufficiency_pct": round(
                    float(last_year.get("solar_kwh", 0.0))
                    / max(1.0, float(last_year.get("house_kwh", 1.0)))
                    * 100,
                    1,
                ),
            },
            "delta": {
                "solar_kwh": _delta("solar_kwh"),
                "import_kwh": _delta("import_kwh"),
                "export_kwh": _delta("export_kwh"),
                "import_cost": _delta("import_cost"),
                "export_earnings": _delta("export_earnings"),
            },
            "delta_pct": {
                "solar_kwh": _delta_pct("solar_kwh"),
                "import_kwh": _delta_pct("import_kwh"),
                "export_kwh": _delta_pct("export_kwh"),
                "import_cost": _delta_pct("import_cost"),
                "export_earnings": _delta_pct("export_earnings"),
            },
        }

    return handle


_CSV_HEADER = (
    "period,solar_kwh,import_kwh,export_kwh,battery_throughput_kwh,"
    "import_cost,export_earnings,net_position,self_sufficiency_pct"
)


def _acc_to_csv_row(period: str, acc) -> str:
    """Format one EnergyAccumulator as a CSV row."""
    import_cost = getattr(acc, "total_import_cost", 0.0)
    export_earn = getattr(acc, "export_earnings", 0.0)
    net = export_earn - import_cost
    ss = getattr(acc, "self_sufficiency_pct", 0.0)
    return (
        f"{period},"
        f"{round(acc.solar_kwh, 3)},"
        f"{round(acc.import_kwh, 3)},"
        f"{round(acc.export_kwh, 3)},"
        f"{round(acc.battery_throughput_kwh, 3)},"
        f"{round(import_cost, 4)},"
        f"{round(export_earn, 4)},"
        f"{round(net, 4)},"
        f"{round(ss, 1)}"
    )


def _snapshot_to_csv_row(index: int, snap: dict) -> str:
    """Format one monthly snapshot dict as a CSV row."""
    import_cost = sum((snap.get("import_cost_by_period") or {}).values())
    export_earn = snap.get("export_earnings", 0.0)
    net = (export_earn or 0.0) - import_cost
    solar = snap.get("solar_kwh", 0.0) or 0.0
    house = snap.get("house_kwh", 0.0) or 1.0
    ss = min(100.0, (solar / house) * 100) if house > 0 else 0.0
    return (
        f"month_snapshot_{index:02d},"
        f"{round(snap.get('solar_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('import_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('export_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('battery_throughput_kwh', 0.0) or 0.0, 3)},"
        f"{round(import_cost, 4)},"
        f"{round(export_earn or 0.0, 4)},"
        f"{round(net, 4)},"
        f"{round(ss, 1)}"
    )


def _make_export_handler(hass: HomeAssistant):
    """Return the export_energy_data service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Export energy history to /config/givenergy_energy_export.csv."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {"file": None, "rows_written": 0, "header": _CSV_HEADER, "rows": []}

        d = coordinator.data
        rows = [_CSV_HEADER]
        rows.append(_acc_to_csv_row("today", d.today))
        rows.append(_acc_to_csv_row("yesterday", d.yesterday))
        rows.append(_acc_to_csv_row("this_week", d.week))
        rows.append(_acc_to_csv_row("this_month", d.month))
        rows.append(_acc_to_csv_row("this_year", d.year))

        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        for idx, snap in enumerate(reversed(snapshots), 1):
            rows.append(_snapshot_to_csv_row(idx, snap))

        csv_content = "\n".join(rows) + "\n"
        file_path = os.path.join(hass.config.config_dir, "givenergy_energy_export.csv")

        def _write() -> None:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(csv_content)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            _LOG.error("Failed to write energy export %s: %s", file_path, err)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dashboard_write_failed",
            ) from err

        n_rows = len(rows) - 1
        _LOG.info("Energy data exported to %s (%d rows)", file_path, n_rows)
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GivEnergy Energy Export Complete",
                "message": (
                    f"Exported {n_rows} rows to `{file_path}`.\n\n"
                    "Rows: today, yesterday, this_week, this_month, this_year"
                    + (
                        f", and {len(snapshots)} completed billing months."
                        if snapshots
                        else "."
                    )
                ),
                "notification_id": "givenergy_energy_export",
            },
            blocking=False,
        )
        return {
            "file": file_path,
            "rows_written": n_rows,
            "header": _CSV_HEADER,
            "rows": rows[1:],
        }

    return handle


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions."""

    async def handle_get_dashboard_yaml(call: ServiceCall) -> None:
        """Write dashboard YAML to /config/givenergy_dashboard.yaml."""
        entries = require_loaded_entries(hass)

        entry = entries[0]
        yaml_output = _build_dashboard_yaml(hass, entry.entry_id)

        file_path = os.path.join(hass.config.config_dir, "givenergy_dashboard.yaml")

        def _write_file() -> None:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(yaml_output)

        try:
            await hass.async_add_executor_job(_write_file)
        except OSError as err:
            _LOG.error("Failed to write dashboard file %s: %s", file_path, err)
            raise ServiceValidationError(
                translation_domain="givenergy_inverter_manager",
                translation_key="dashboard_write_failed",
            ) from err

        _LOG.info("Dashboard YAML written to %s", file_path)

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GivEnergy Dashboard Ready",
                "message": (
                    f"Dashboard written to `{file_path}`.\n\n"
                    "**To apply (UI mode):**\n"
                    "1. Settings → Dashboards → Add Dashboard → Blank\n"
                    "2. Three-dot menu → Edit dashboard → Raw configuration editor\n"
                    "3. Paste the contents of `givenergy_dashboard.yaml`\n\n"
                    "**To apply (YAML mode):** add to `configuration.yaml`:\n"
                    "```yaml\n"
                    "lovelace:\n"
                    "  dashboards:\n"
                    "    givenergy:\n"
                    "      mode: yaml\n"
                    "      filename: givenergy_dashboard.yaml\n"
                    "      title: GivEnergy Inverter Manager\n"
                    "      icon: mdi:solar-power-variant\n"
                    "      show_in_sidebar: true\n"
                    "```\n\n"
                    "Run this action again after reconfiguring to regenerate the file."
                ),
                "notification_id": "givenergy_dashboard_yaml",
            },
            blocking=False,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DASHBOARD_YAML,
        handle_get_dashboard_yaml,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_GET_DASHBOARD_YAML)

    async def handle_suggest_appliance(call) -> None:
        """Evaluate whether now is a good time to run a high-load appliance."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return

        appliance_name: str = call.data["appliance_name"]
        appliance_power_w: float = float(call.data["appliance_power_w"])
        data = coordinator.data

        recommended, reason = suggest_appliance_run(
            solar_power_w=data.solar_power_w,
            house_load_w=data.house_load_w,
            battery_soc=data.battery_soc,
            battery_power_w=data.battery_power_w,
            appliance_power_w=appliance_power_w,
            appliance_name=appliance_name,
            rate_period_name=data.current_rate_name,
            rate=data.current_rate,
            export_rate=coordinator.export_rate,
        )

        verdict = "Good time to run" if recommended else "Not recommended right now"
        notification_id = f"givenergy_appliance_{appliance_name.lower().replace(' ', '_')}"
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"Appliance Suggestion — {appliance_name}",
                    "message": f"**{verdict}**\n\n{reason}",
                    "notification_id": notification_id,
                },
                blocking=False,
            )
        )
        _LOG.info(
            "Appliance suggestion for %r: %s — %s",
            appliance_name,
            verdict,
            reason,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUGGEST_APPLIANCE,
        handle_suggest_appliance,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_SUGGEST_APPLIANCE)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROI_SUMMARY,
        _make_roi_summary_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_GET_ROI_SUMMARY)

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE_TARIFF,
        _make_compare_tariff_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_COMPARE_TARIFF)

    hass.services.async_register(
        DOMAIN,
        SERVICE_YEAR_ON_YEAR,
        _make_year_on_year_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_YEAR_ON_YEAR)

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_ENERGY_DATA,
        _make_export_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_EXPORT_ENERGY_DATA)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when the integration is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_GET_DASHBOARD_YAML)
    hass.services.async_remove(DOMAIN, SERVICE_SUGGEST_APPLIANCE)
    hass.services.async_remove(DOMAIN, SERVICE_GET_ROI_SUMMARY)
    hass.services.async_remove(DOMAIN, SERVICE_COMPARE_TARIFF)
    hass.services.async_remove(DOMAIN, SERVICE_YEAR_ON_YEAR)
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_ENERGY_DATA)
