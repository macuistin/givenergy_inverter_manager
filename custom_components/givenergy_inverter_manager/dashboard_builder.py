"""
dashboard_builder.py - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict, then serialised with PyYAML. The
get_dashboard_yaml service writes the YAML to a file.

The generated dashboard has four views:
  1. Power Flow   - live animated energy flow (power-flow-card-plus from HACS)
  2. Today        - daily energy totals, cost breakdown, self-sufficiency
  3. Battery      - battery health, charge decision, night survival
  4. Controls     - charge target slider, switches, EV charger state

Power flow view requires power-flow-card-plus from HACS:
  https://github.com/flixlix/power-flow-card-plus

The immersion charts need apexcharts-card from HACS:
  https://github.com/RomRider/apexcharts-card

All other views use only built-in HA Lovelace cards.
"""

from __future__ import annotations

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_IMMERSION_TEMP_SENSOR, DOMAIN

SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"


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


def build_dashboard_yaml(hass: HomeAssistant, entry_id: str) -> str:
    """Return the dashboard as YAML text, with a short header comment."""
    return _DASHBOARD_HEADER + _dump_yaml(build_dashboard(hass, entry_id))


def build_dashboard(hass: HomeAssistant, entry_id: str) -> dict:
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
