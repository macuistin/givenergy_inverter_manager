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

import textwrap

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .core.rules import suggest_appliance_run
from .logging import get_logger

_LOG = get_logger(__name__)

SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"
SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"


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
    current_rate_period = e("current_rate_period")
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
    ev_state = e("ev_charger_state")
    ev_power = _find_ev_charger_power(hass, e("ev_power"))
    ev_session = e("ev_session_energy")
    ev_draining = e("ev_draining_battery")
    ev_protection_reason = e("ev_protection_reason")

    # ── dry run sensor IDs ───────────────────────────────────────────────────────
    dry_run_active = e("dry_run_active")
    dry_run_skipped = e("dry_run_last_skipped")

    # ── switch / number entity IDs ────────────────────────────────────────────
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
                # Requires: https://github.com/flixlix/power-flow-card-plus (HACS)
                entities:
                  solar:
                    entity: {solar_power}
                  battery:
                    entity: {battery_power}
                    state_of_charge: {battery_soc}
                    display_zero_tolerance: 10
                  grid:
                    entity: {grid_power}
                  home:
                    entity: {house_load}
                  individual:
                  - entity: {ev_power}
                    name: EV Charger
                    icon: mdi:car-electric
                    color: "#4CAF50"
                    display_zero: false
                  - entity: {immersion_power}
                    name: Immersion
                    icon: mdi:water-boiler
                    color: "#FF9800"
                    display_zero: false
                title: Live Power Flow
                kw_decimals: 1
                w_decimals: 0
                min_flow_rate: 0.75
                max_flow_rate: 6
                watt_threshold: 1000

              - type: grid
                square: false
                columns: 3
                cards:
                  - type: entity
                    entity: {current_rate_period}
                    name: Rate Period
                    icon: mdi:clock-outline
                  - type: entity
                    entity: {current_rate}
                    name: Current Rate
                    icon: mdi:currency-eur
                  - type: entity
                    entity: {is_clipping}
                    name: Clipping
                    icon: mdi:alert-circle-outline

          # ── View 2: Today ────────────────────────────────────────────────────
          - title: Today
            icon: mdi:calendar-today
            path: today
            cards:
              - type: heading
                heading: Energy Today
                heading_style: title

              - type: grid
                square: false
                columns: 2
                cards:
                  - type: entity
                    entity: {solar_today}
                    name: Solar Generated
                    icon: mdi:solar-power
                  - type: entity
                    entity: {import_today}
                    name: Grid Import
                    icon: mdi:transmission-tower-import
                  - type: entity
                    entity: {export_today}
                    name: Grid Export
                    icon: mdi:transmission-tower-export
                  - type: entity
                    entity: {zappi_today}
                    name: EV Charging
                    icon: mdi:car-electric
                  - type: entity
                    entity: {immersion_today}
                    name: Immersion Heater
                    icon: mdi:water-boiler

              - type: heading
                heading: Cost Breakdown
                heading_style: title

              - type: entities
                entities:
                  - entity: {import_cost_today}
                    name: Import Cost
                    icon: mdi:cash-minus
                  - entity: {export_earnings}
                    name: Export Earnings
                    icon: mdi:cash-plus
                  - entity: {zappi_cost_today}
                    name: EV Charging Cost
                    icon: mdi:car-electric
                  - entity: {immersion_cost_today}
                    name: Immersion Cost
                    icon: mdi:water-boiler
                  - entity: {house_cost_today}
                    name: Rest-of-House Cost
                    icon: mdi:home

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

              - type: heading
                heading: Self-Sufficiency
                heading_style: title

              - type: grid
                square: false
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

              - type: heading
                heading: Bill Prediction
                heading_style: title

              - type: entities
                entities:
                  - entity: {accrued_bill}
                    name: Accrued This Period
                    icon: mdi:receipt
                  - entity: {projected_bill}
                    name: Projected Total
                    icon: mdi:receipt-text-outline
                  - entity: {days_remaining}
                    name: Days Remaining
                    icon: mdi:calendar-end

          # ── View 3: Battery ──────────────────────────────────────────────────
          - title: Battery
            icon: mdi:battery-charging
            path: battery
            cards:
              - type: heading
                heading: Current State
                heading_style: title

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

              - type: heading
                heading: Tonight's Charge Plan
                heading_style: title

              - type: entities
                entities:
                  - entity: {charge_target}
                    name: Recommended Target
                    icon: mdi:battery-charging-80
                  - entity: {charge_reason}
                    name: Reason
                    icon: mdi:information-outline
                  - entity: {charge_cost}
                    name: Estimated Charge Cost
                    icon: mdi:currency-eur
                  - entity: {soc_at_sunrise}
                    name: Estimated SoC at Sunrise
                    icon: mdi:weather-sunny
                  - entity: {survival_reason}
                    name: Night Survival Status
                    icon: mdi:moon-waning-crescent

              - type: heading
                heading: Battery Health
                heading_style: title

              - type: entities
                entities:
                  - entity: {battery_cycles}
                    name: Total Cycles
                    icon: mdi:battery-sync
                  - entity: {battery_life}
                    name: Estimated Life Remaining
                    icon: mdi:battery-heart
                  - entity: {days_since_full}
                    name: Days Since Full Charge
                    icon: mdi:battery-100

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

              - type: heading
                heading: Overnight Charging
                heading_style: title

              - type: entities
                entities:
                  - entity: {sw_enable_charge_target}
                    name: Enable Charge Target Override
                  - entity: {num_charge_target}
                    name: Overnight Charge Target
                  - entity: {sw_skip_charge}
                    name: Force Skip Charge Tonight

              - type: heading
                heading: Immersion Heater
                heading_style: title

              - type: entities
                entities:
                  - entity: {sw_auto_immersion}
                    name: Auto Immersion Divert
                  - entity: {sw_immersion_mgd}
                    name: Immersion Heater (Managed)
                  - entity: {immersion_reason}
                    name: Divert Reason
                    icon: mdi:water-boiler

              - type: heading
                heading: EV Charger
                heading_style: title

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
                    icon: mdi:battery-charging-outline
                  - entity: {ev_draining}
                    name: Draining Battery
                    icon: mdi:battery-arrow-down
                  - entity: {ev_protection_reason}
                    name: Protection Status
                    icon: mdi:shield-check
    """)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the get_dashboard_yaml service."""

    @callback
    def handle_get_dashboard_yaml(call: ServiceCall) -> None:
        """Return pre-filled Lovelace YAML for the first registered entry."""
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOG.error("No GivEnergy Inverter Manager entries found")
            return

        entry = entries[0]
        yaml_output = _build_dashboard_yaml(hass, entry.entry_id)

        # Fire a persistent notification so the user can copy the YAML
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "GivEnergy Dashboard YAML",
                    "message": (
                        "Copy the YAML below and paste it into a new blank dashboard "
                        "(Settings → Dashboards → new dashboard → Raw configuration editor).\n\n"
                        "**Note:** View 1 (Power Flow) requires "
                        "[power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus) "
                        "from HACS. All other views use only built-in HA cards.\n\n"
                        f"```yaml\n{yaml_output}\n```"
                    ),
                    "notification_id": "givenergy_dashboard_yaml",
                },
                blocking=False,
            )
        )
        _LOG.info("Dashboard YAML generated for entry %s — check Notifications", entry.title)

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
            appliance_power_w=appliance_power_w,
            appliance_name=appliance_name,
            rate_period_name=data.current_rate_name,
            rate=data.current_rate,
            export_rate=data.export_rate if hasattr(data, "export_rate") else 0.0,
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


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when the integration is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_GET_DASHBOARD_YAML)
    hass.services.async_remove(DOMAIN, SERVICE_SUGGEST_APPLIANCE)
