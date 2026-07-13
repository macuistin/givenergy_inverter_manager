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
import textwrap

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .core.rules import suggest_appliance_run
from .logging import get_logger

_LOG = get_logger(__name__)

SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"
SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"
SERVICE_COMPARE_TARIFF = "compare_tariff"
SERVICE_YEAR_ON_YEAR = "year_on_year_summary"
SERVICE_EXPORT_ENERGY_DATA = "export_energy_data"
SERVICE_GET_ROI_SUMMARY = "get_roi_summary"


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


def _build_immersion_section(
    immersion_temp_sensor: str,
    immersion_reason: str,
    num_target: str,
    num_min: str,
    num_gap: str,
    immersion_today: str,
) -> str:
    """Build the immersion section for the power flow tab.

    Returns YAML for a vertical-stack with:
      - apexcharts-card: 12h temperature history (water, target, minimum)
      - tile card: current divert reason
      - apexcharts-card: 12h immersion energy accumulated today

    Requires apexcharts-card from HACS (github.com/RomRider/apexcharts-card).
    Inserted at column 14 in the parent template — first line gets that indent
    for free; every subsequent line carries its own.
    """
    if not immersion_temp_sensor:
        return "# Immersion section: no temperature sensor configured in settings"

    n = "\n"
    p16 = "                "  # 16 sp — vertical-stack props / cards list
    p18 = "                  "  # 18 sp — card props
    p20 = "                    "  # 20 sp — nested props
    p22 = "                      "  # 22 sp — deeply nested

    apex_cfg = (
        f"{p18}apex_config:{n}"
        f"{p20}chart:{n}"
        f"{p22}height: 150{n}"
        f"{p22}zoom:{n}"
        f"{p22}  enabled: false{n}"
        f"{p20}tooltip:{n}"
        f"{p22}shared: true{n}"
        f"{p22}followCursor: true{n}"
        f"{p20}stroke:{n}"
        f"{p22}curve: smooth{n}"
        f"{p22}width: 2{n}"
        f"{p20}markers:{n}"
        f"{p22}size: 0{n}"
        f"{p22}hover:{n}"
        f"{p22}  size: 5{n}"
        f"{p20}legend:{n}"
        f"{p22}show: false{n}"
    )

    return (
        f"- type: vertical-stack{n}"
        f"{p16}cards:{n}"
        # Temperature history
        f"{p16}- type: custom:apexcharts-card{n}"
        f"{p18}header:{n}"
        f"{p20}show: true{n}"
        f"{p20}title: Immersion Temperature (12h){n}"
        f"{p18}graph_span: 12h{n}" + apex_cfg + f"{p18}series:{n}"
        f"{p20}- entity: {immersion_temp_sensor}{n}"
        f"{p22}name: Water{n}"
        f'{p22}color: "#03a9f4"{n}'
        f"{p22}stroke_width: 2{n}"
        f"{p20}- entity: {num_target}{n}"
        f"{p22}name: Target{n}"
        f'{p22}color: "#f44336"{n}'
        f"{p22}stroke_width: 1{n}"
        f"{p20}- entity: {num_min}{n}"
        f"{p22}name: Minimum{n}"
        f'{p22}color: "#ff9800"{n}'
        f"{p22}stroke_width: 1{n}"
        # Divert reason tile
        f"{p16}- type: tile{n}"
        f"{p18}entity: {immersion_reason}{n}"
        f"{p18}name: ' '{n}"
        f"{p18}show_entity_picture: false{n}"
        f"{p18}hide_state: false{n}"
        f"{p18}vertical: false{n}"
        f"{p18}features_position: bottom{n}"
        # Immersion energy accumulated today
        f"{p16}- type: custom:apexcharts-card{n}"
        f"{p18}header:{n}"
        f"{p20}show: true{n}"
        f"{p20}title: Power{n}"
        f"{p18}graph_span: 12h{n}"
        f"{p18}yaxis:{n}"
        f"{p20}- min: 0{n}" + apex_cfg + f"{p18}series:{n}"
        f"{p20}- entity: {immersion_today}{n}"
        f"{p22}name: Immersion Power Today{n}"
        f'{p22}color: "#03a9f4"{n}'
        f"{p22}stroke_width: 2"
    )


def _build_dashboard_yaml(hass: HomeAssistant, entry_id: str) -> str:
    """
    Build complete Lovelace YAML for all four views.

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

    # ── immersion config (temp sensor and number entities) ───────────────────
    from .const import CONF_IMMERSION_TEMP_SENSOR

    _entry_cfg: dict = {}
    for _ce in hass.config_entries.async_entries("givenergy_inverter_manager"):
        if _ce.entry_id == entry_id:
            _entry_cfg = {**_ce.data, **_ce.options}
            break
    immersion_temp_sensor = _entry_cfg.get(CONF_IMMERSION_TEMP_SENSOR, "")
    num_immersion_target = e("immersion_target_temp")
    num_immersion_min = e("immersion_min_temp")
    num_immersion_gap = e("immersion_hysteresis")
    _immersion_section = _build_immersion_section(
        immersion_temp_sensor,
        immersion_reason,
        num_immersion_target,
        num_immersion_min,
        num_immersion_gap,
        immersion_today,
    )

    # ── dry run sensor IDs ───────────────────────────────────────────────────────
    dry_run_active = e("dry_run_active")
    dry_run_skipped = e("dry_run_last_skipped")

    # ── switch / number entity IDs ────────────────────────────────────────────
    btn_refresh_dashboard = e("refresh_dashboard")
    sw_enable_charge_target = e("charge_target_override_enabled")
    sw_auto_immersion = e("auto_immersion")
    sw_immersion_mgd = e("immersion_managed")
    sw_skip_charge = e("skip_charge_override")
    num_charge_target = e("charge_target_override")

    return textwrap.dedent(f"""\
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

        views:

          # ── View 1: Live Power Flow ──────────────────────────────────────────
          - title: Power Flow
            icon: mdi:solar-power-variant
            path: power-flow
            cards:
              - type: custom:power-flow-card-plus
                entities:
                  solar:
                    entity: {solar_power}
                    color_icon: false
                    color_value: false
                    invert_state: false
                    secondary_info_entity: {is_clipping}
                    secondary_info:
                      template: |-
                        {{{{- '·⚡Clip' if
                                  states('{is_clipping}') ==
                                  'clipping' else '' }}}}
                  battery:
                    entity: {battery_power}
                    state_of_charge: {battery_soc}
                    show_state_of_charge: true
                  grid:
                    entity: {grid_power}
                    use_metadata: false
                    invert_state: false
                    display_state: one_way
                    secondary_info:
                      entity: {live_grid_cost_rate}
                      icon: mdi:cash-clock
                      decimals: 4
                      display_zero: true
                      color_value: false
                      unit_of_measurement: " "
                  home:
                    entity: {house_load}
                    subtract_individual: false
                    hide: false
                  individual:
                  - entity: {ev_power}
                    name: Car Charger
                    icon: mdi:car-electric
                    display_zero: false
                    color: "#4CAF50"
                  - entity: {immersion_power}
                    name: Immersion
                    icon: mdi:water-boiler
                    display_zero: false
                    color: "#FF9800"
                title: Live Power Flow
                min_flow_rate: 0.75
                max_flow_rate: 6
                display_zero_lines:
                  mode: transparency
                  transparency: 75
                  grey_color:
                  - 189
                  - 189
                  - 189
                allow_layout_break: false
                kilo_threshold: 1000
                base_decimals: 0
                kilo_decimals: 1
                disable_dots: false
                clickable_entities: true
                no_labels: false

              {_immersion_section}

          # ── View 2: Today ────────────────────────────────────────────────────
          - title: Today
            icon: mdi:calendar-today
            path: today
            cards:
              - show_name: true
                show_icon: true
                show_state: true
                type: glance
                title: Energy Today
                entities:
                  - entity: {solar_today}
                    name: Generated
                  - entity: {import_today}
                    name: Import
                  - entity: {export_today}
                    name: Export
                  - entity: {zappi_today}
                    name: EV
                  - entity: {immersion_today}
                    name: Immersion

              - type: entities
                entities:
                  - entity: {current_rate}
                    name: Current Rate
                  - entity: {current_rate_period}
                    name: Rate Period
                  - type: divider
                  - entity: {import_cost_today}
                    name: Import Cost
                  - entity: {export_earnings}
                    name: Export Earnings
                  - entity: {zappi_cost_today}
                    name: EV Charging Cost
                  - entity: {immersion_cost_today}
                    name: Immersion Cost
                  - entity: {immersion_savings}
                    name: Immersion Savings
                  - entity: {house_cost_today}
                    name: Rest-of-House Cost
                title: Cost Breakdown

              - type: history-graph
                title: Cost build — today
                hours_to_show: 24
                entities:
                  - entity: {import_cost_today}
                    name: Grid Import
                  - entity: {house_cost_today}
                    name: Rest of House
                  - entity: {zappi_cost_today}
                    name: EV Charging
                  - entity: {immersion_cost_today}
                    name: Immersion
                  - entity: {export_earnings}
                    name: Export Earnings

              - type: history-graph
                title: Solar generation — today
                hours_to_show: 24
                entities:
                  - entity: {solar_today}
                    name: Actual

              - type: entities
                title: Solar vs Forecast
                entities:
                  - entity: {solar_today}
                    name: Generated today
                  - entity: {solar_forecast_today}
                    name: Today's forecast
                  - entity: {solar_vs_forecast_pct}
                    name: Tracking
                    icon: mdi:chart-line
                  - entity: {forecast_accuracy_yesterday}
                    name: Yesterday's accuracy

              - square: false
                type: grid
                columns: 2
                cards:
                  - type: gauge
                    entity: {self_sufficiency}
                    name: Self-Sufficiency
                    min: 0
                    max: 100
                    severity:
                      green: 60
                      yellow: 30
                      red: 0
                  - type: gauge
                    entity: {self_consumption}
                    name: Self-Consumption
                    min: 0
                    max: 100
                    severity:
                      green: 70
                      yellow: 40
                      red: 0
                title: Self Sufficiency

              - type: entities
                entities:
                  - entity: {accrued_bill}
                    name: Accrued This Period
                  - entity: {projected_bill}
                    name: Projected Total
                  - entity: {days_remaining}
                    name: Days Remaining
                title: Bill Prediction
                show_header_toggle: false
                state_color: false

          # ── View 3: Battery ──────────────────────────────────────────────────
          - title: Battery
            icon: mdi:battery-charging
            path: battery
            cards:
              - type: gauge
                entity: {battery_soc}
                name: Battery SoC
                min: 0
                max: 100
                needle: true
                severity:
                  green: 50
                  yellow: 20
                  red: 0

              - type: history-graph
                title: Battery SoC — 24h
                hours_to_show: 24
                entities:
                  - entity: {battery_soc}
                    name: SoC
                  - entity: {battery_power}
                    name: Power (W)

              - type: entities
                entities:
                  - entity: {battery_power}
                    name: Charge / Discharge Power
                  - entity: {charge_target}
                    name: Recommended Target Tonight
                  - entity: {charge_reason}
                    name: Reason
                    icon: mdi:information-outline
                  - entity: {charge_cost}
                    name: Estimated Charge Cost
                  - entity: {soc_at_sunrise}
                    name: Estimated SoC at Sunrise
                  - entity: {survival_reason}
                    name: Night Survival Status
                    icon: mdi:moon-waning-crescent
                  - entity: {cheap_rate_floor}
                    name: Cheap Rate Floor
                    icon: mdi:floor-plan
                title: Tonight's Charge Plan

              - type: entities
                entities:
                  - entity: {battery_cycles}
                    name: Total Cycles
                  - entity: {battery_life}
                    name: Estimated Life Remaining
                  - entity: {days_since_full}
                    name: Days Since Full Charge
                  - entity: {inverter_temp}
                    name: Inverter Temperature
                  - entity: {inverter_temp_status}
                    name: Inverter Status
                    icon: mdi:thermometer-alert
                title: Battery Health

          # ── View 4: Controls ─────────────────────────────────────────────────
          - title: Controls
            icon: mdi:tune
            path: controls
            cards:
              - type: conditional
                conditions:
                  - condition: state
                    entity: {dry_run_active}
                    state: "True"
                card:
                  type: markdown
                  content: >
                    ## ⚠️ Dry Run Mode Active

                    This integration is in **simulation mode**. All sensor
                    values update normally and charge decisions are calculated,
                    but **no commands are sent to your inverter or EV charger**.

                    To go live, disable Dry Run in Settings → Integrations →
                    GivEnergy Inverter Manager → Configure.

              - type: conditional
                conditions:
                  - condition: state
                    entity: {dry_run_active}
                    state: "True"
                card:
                  type: entities
                  title: Dry Run Status
                  entities:
                    - entity: {dry_run_active}
                      name: Dry Run Mode
                      icon: mdi:test-tube
                    - entity: {dry_run_skipped}
                      name: Last Skipped Action
                      icon: mdi:skip-next-circle-outline

              - type: entities
                entities:
                  - entity: {sw_enable_charge_target}
                    name: Enable Charge Target Override
                  - entity: {num_charge_target}
                    name: Overnight Charge Target
                  - entity: {sw_skip_charge}
                    name: Force Skip Charge Tonight
                title: Overnight Charging

              - type: entities
                entities:
                  - entity: {sw_auto_immersion}
                    name: Auto Immersion Divert
                  - entity: {sw_immersion_mgd}
                    name: Immersion Heater (Managed)
                  - entity: {immersion_reason}
                    name: Divert Reason
                    icon: mdi:water-boiler
                  - type: divider
                  - entity: {num_immersion_target}
                    name: Target Temperature
                  - entity: {num_immersion_min}
                    name: Minimum Temperature
                  - entity: {num_immersion_gap}
                    name: Restart Gap
                title: Immersion Heater

              - type: entities
                entities:
                  - entity: {ev_state}
                    name: Charger State
                    icon: mdi:ev-station
                  - entity: {ev_power}
                    name: Charge Power
                    icon: mdi:lightning-bolt
                  - entity: {ev_session}
                    name: Session Energy
                  - entity: {ev_draining}
                    name: Draining Battery
                  - entity: {ev_protection_reason}
                    name: Protection Status
                    icon: mdi:shield-check
                  - entity: {ev_charging_source}
                    name: Charging Source
                  - entity: {ev_solar_surplus}
                    name: Solar Surplus Available
                title: EV Charger

              - type: button
                entity: {btn_refresh_dashboard}
                name: Refresh Dashboard
                icon: mdi:view-dashboard-edit
                tap_action:
                  action: perform-action
                  perform_action: {DOMAIN}.get_dashboard_yaml
                  data: {{}}
        """)


def _make_roi_summary_handler(hass: HomeAssistant):
    """Return the get_roi_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Return ROI metrics for today/week/month/year and battery health."""
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries or entries[0].runtime_data is None:
            return {}
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


def _make_compare_tariff_handler(hass: HomeAssistant):
    """Return the compare_tariff service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare current billing period cost against a flat-rate alternative tariff.

        Service data fields:
          rate            — flat import rate of the comparison tariff (€/kWh, required)
          standing_charge — daily standing charge of the comparison tariff (€/day, default 0)
          export_rate     — export rate of the comparison tariff (€/kWh, default 0)
        """
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries or entries[0].runtime_data is None:
            return {}
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {}

        d = coordinator.data
        alt_rate = float(call.data["rate"])
        alt_standing = float(call.data.get("standing_charge", 0.0))
        alt_export_rate = float(call.data.get("export_rate", 0.0))

        days = d.days_in_period
        import_kwh = d.month.import_kwh
        export_kwh = d.month.export_kwh

        actual_import_cost = d.month.total_import_cost
        actual_export_earnings = d.month.export_earnings
        actual_net = actual_import_cost - actual_export_earnings

        alt_import_cost = import_kwh * alt_rate
        alt_export_earnings = export_kwh * alt_export_rate
        alt_standing_total = alt_standing * days
        alt_net = alt_import_cost + alt_standing_total - alt_export_earnings

        return {
            "period_days": days,
            "import_kwh": round(import_kwh, 3),
            "export_kwh": round(export_kwh, 3),
            "current_tariff": {
                "import_cost": round(actual_import_cost, 4),
                "export_earnings": round(actual_export_earnings, 4),
                "net_cost": round(actual_net, 4),
            },
            "comparison_tariff": {
                "rate": alt_rate,
                "standing_charge_per_day": alt_standing,
                "export_rate": alt_export_rate,
                "import_cost": round(alt_import_cost, 4),
                "standing_charges": round(alt_standing_total, 4),
                "export_earnings": round(alt_export_earnings, 4),
                "net_cost": round(alt_net, 4),
            },
            "saving": round(actual_net - alt_net, 4),
        }

    return handle


def _make_year_on_year_handler(hass: HomeAssistant):
    """Return the year_on_year_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare current billing month against the same month one year ago."""
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries or entries[0].runtime_data is None:
            return {}
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

    async def handle(call: ServiceCall) -> None:
        """Export energy history to /config/givenergy_energy_export.csv."""
        from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries or entries[0].runtime_data is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_config_entry",
            )
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return

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

    return handle


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the get_dashboard_yaml service."""

    async def handle_get_dashboard_yaml(call: ServiceCall) -> None:
        """Write dashboard YAML to /config/givenergy_dashboard.yaml."""
        from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(
                translation_domain="givenergy_inverter_manager",
                translation_key="no_config_entry",
            )

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
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries or entries[0].runtime_data is None:
            return
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


    from homeassistant.core import SupportsResponse  # noqa: PLC0415

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
