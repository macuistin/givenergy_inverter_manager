#!/usr/bin/env python3
"""Generate docs/sensors.md from the sensor descriptions in sensor_descriptions/.

The sensor facts (name, key, unit, device class, state class, enabled by
default, midnight reset) are read from the source with ``ast`` and from
``translations/en.json``, so the table follows the code. Home Assistant is
not imported.

The one hand-written part is the "What it reports" column. It lives in
DESCRIPTIONS below. A sensor with no entry gets an empty cell, so a new
sensor never breaks the generator.

Usage:
    python scripts/gen_sensor_docs.py            # rewrite docs/sensors.md
    python scripts/gen_sensor_docs.py --check    # exit 1 if the file is out of date
    python scripts/gen_sensor_docs.py --stdout   # print instead of writing
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "givenergy_inverter_manager"
DESCRIPTIONS_DIR = PKG / "sensor_descriptions"
EN_JSON = PKG / "translations" / "en.json"
OUTPUT = ROOT / "docs" / "sensors.md"

DESCRIPTION_CLASS = "GivEnergyManagerSensorDescription"
TABLE_NAME = "SENSOR_DESCRIPTIONS"

UNITS = {
    "WATT": "W",
    "KILO_WATT_HOUR": "kWh",
    "PERCENTAGE": "%",
    "CELSIUS": "°C",
    "CURRENCY_UNIT": "currency",
}

# Group order. Each sensor lands in the first group that claims it: an exact
# key in KEY_GROUPS, then a key suffix in SUFFIX_GROUPS, else "Other".
GROUPS: dict[str, str] = {
    "Live power and flow": (
        "Updated every 30 seconds. Power values are in watts. Grid Power is positive when "
        "importing."
    ),
    "Tariff and rate": "Read from the tariff you configured. See [Tariff](tariff.md).",
    "Energy today": (
        "Accumulated since local midnight. They report `last_reset` as the most recent midnight. "
        "See [Long-term statistics](long-term-statistics.md)."
    ),
    "Cost and savings today": "Money sensors use the currency symbol you chose in the tariff.",
    "Efficiency today": "Percentages worked out from today's totals.",
    "Bill": "Estimates for the current bill period. See [Tariff](tariff.md#bill-line-items).",
    "Battery": "Health, wear and state of the battery.",
    "Charge plan and night survival": "Outputs of the overnight charge calculation.",
    "Immersion": (
        "Output of the immersion divert rule, the water temperature and the oil water heating "
        "advice. The water temperature sensor exists only with a temperature sensor set. The "
        "cheapest source sensor exists only with an oil price and an immersion switch set."
    ),
    "EV charger": (
        "These sensors exist only while a supported charger is discovered, and appear when "
        "discovery first finds one. The ones marked `EV charger needed` are unavailable "
        "while the charger is not reporting."
    ),
    "Solar forecast": "Needs a forecast sensor in the options to be meaningful.",
    "Carbon intensity": "Needs a carbon intensity sensor in the options.",
    "Yesterday": (
        "Yesterday's totals, copied from today's accumulator at midnight. They have no state "
        "class, so Home Assistant keeps no long-term statistics for them."
    ),
    "This week": "Resets at midnight on Monday. Reports `last_reset` as the start of the week.",
    "This month": (
        "Resets at midnight on the bill start day chosen at setup. Reports `last_reset` as the "
        "start of the bill period."
    ),
    "This year and trailing 12 months": (
        "Year sensors reset at midnight on 1 January and report `last_reset` as the start of the "
        "year. Trailing 12-month sensors add up the last 12 completed bill periods and have no "
        "state class."
    ),
    "HTML reports": (
        "The state is a one-line summary. The `html` attribute holds a styled report for a "
        "Markdown card. See [Dashboard](dashboard.md#html-report-cards)."
    ),
    "Dry run and diagnostics": "",
    "Other": "",
}

KEY_GROUPS: dict[str, str] = {
    **dict.fromkeys(
        (
            "solar_power",
            "battery_soc",
            "battery_power",
            "immersion_power",
            "grid_power",
            "house_load",
            "rest_of_house_load",
            "grid_power_direction",
            "solar_power_pct_of_max",
            "net_solar_surplus_w",
            "battery_power_direction",
            "is_clipping",
            "inverter_temperature",
            "inverter_temperature_status",
        ),
        "Live power and flow",
    ),
    **dict.fromkeys(
        (
            "current_rate",
            "current_rate_period",
            "live_grid_cost_rate",
            "next_cheap_rate_start",
            "hours_to_cheap_rate",
            "cheapest_rate",
            "cheapest_rate_period",
            "is_on_cheapest_rate",
            "is_on_base_rate",
            "minutes_remaining_in_period",
            "rate_savings_vs_daytime",
            "avg_import_rate_today",
            "avg_import_rate_this_week",
            "avg_import_rate_this_month",
        ),
        "Tariff and rate",
    ),
    **dict.fromkeys(
        (
            "solar_today",
            "import_today",
            "grid_to_battery_today",
            "export_today",
            "house_kwh_today",
            "zappi_today",
            "immersion_today",
            "battery_charge_kwh_today",
            "battery_discharge_kwh_today",
            "battery_throughput_kwh_today",
            "import_kwh_cheap_today",
            "import_kwh_peak_today",
            "immersion_solar_kwh_today",
            "self_consumed_kwh_today",
            "missed_solar_today",
            "inverter_derating_today_minutes",
        ),
        "Energy today",
    ),
    **dict.fromkeys(
        (
            "import_cost_today",
            "export_earnings_today",
            "zappi_cost_today",
            "house_cost_today",
            "immersion_cost_today",
            "import_cost_cheap_today",
            "import_cost_peak_today",
            "immersion_savings_today",
            "saving_vs_grid_today",
            "net_saving_today",
            "net_position_today",
        ),
        "Cost and savings today",
    ),
    **dict.fromkeys(
        (
            "self_sufficiency",
            "solar_share",
            "self_consumption",
            "peak_import_fraction_today",
            "solar_capture_efficiency_today",
            "battery_roundtrip_efficiency_today",
        ),
        "Efficiency today",
    ),
    **dict.fromkeys(
        ("accrued_bill", "projected_bill", "days_remaining_in_period", "days_in_period"),
        "Bill",
    ),
    **dict.fromkeys(
        (
            "battery_cycles",
            "battery_remaining_life",
            "days_since_full_charge",
            "battery_years_remaining",
            "battery_usable_capacity_kwh",
            "battery_kwh_available",
            "battery_state",
            "battery_cycle_cost_per_kwh",
            "battery_life_consumed_today",
            "battery_throughput_budget_pct",
            "battery_throughput_budget_status",
            "register_write_count",
        ),
        "Battery",
    ),
    **dict.fromkeys(
        (
            "overnight_charge_target",
            "overnight_charge_reason",
            "overnight_charge_window",
            "overnight_charge_cost",
            "estimated_soc_at_sunrise",
            "night_survival_reason",
            "night_survival_confidence",
            "cheap_rate_floor_status",
        ),
        "Charge plan and night survival",
    ),
    **dict.fromkeys(
        (
            "immersion_divert_reason",
            "immersion_water_temperature",
            "water_heating_cheapest_source",
        ),
        "Immersion",
    ),
    **dict.fromkeys(
        (
            "ev_charger_state",
            "ev_power",
            "ev_session_energy",
            "ev_km_charged_today",
            "ev_cost_per_km_today",
            "ev_draining_battery",
            "ev_protection_reason",
            "ev_charging_source",
            "ev_solar_surplus_available",
        ),
        "EV charger",
    ),
    **dict.fromkeys(
        (
            "solar_forecast_kwh_today",
            "solar_forecast_raw_today",
            "solar_actual_vs_forecast_pct",
            "yesterday_forecast_accuracy_pct",
            "forecast_accuracy_7day_avg_pct",
        ),
        "Solar forecast",
    ),
    **dict.fromkeys(("carbon_intensity", "carbon_intensity_status"), "Carbon intensity"),
    **dict.fromkeys(("today_summary", "charge_plan", "week_summary"), "HTML reports"),
    **dict.fromkeys(
        ("dry_run_active", "dry_run_last_skipped", "integration_version"),
        "Dry run and diagnostics",
    ),
    "net_position_this_month": "This month",
}

SUFFIX_GROUPS: tuple[tuple[str, str], ...] = (
    ("_yesterday", "Yesterday"),
    ("_this_week", "This week"),
    ("_this_month", "This month"),
    ("_this_year", "This year and trailing 12 months"),
    ("_trailing_12m", "This year and trailing 12 months"),
)

DESCRIPTIONS: dict[str, str] = {
    "solar_power": "Current solar generation.",
    "battery_soc": "Battery state of charge.",
    "battery_power": "Positive while charging, negative while discharging.",
    "immersion_power": "Configured element wattage while the immersion switch is on, else 0.",
    "grid_power": "Positive while importing, negative while exporting.",
    "house_load": "House load as read from the GivTCP load sensor.",
    "rest_of_house_load": "House load minus EV charger power and immersion power, floored at 0.",
    "grid_power_direction": "Importing, Exporting or Balanced (within 50 W of zero).",
    "solar_power_pct_of_max": "Solar power as a percentage of the configured inverter maximum.",
    "net_solar_surplus_w": (
        "Smoothed solar power minus house load, with the immersion's own draw added back, "
        "floored at 0. Battery charging is not subtracted. Drives the EV signals."
    ),
    "battery_kwh_available": "Battery state of charge times the configured capacity.",
    "battery_power_direction": "Charging, Discharging or Idle (within 50 W of zero).",
    "is_clipping": "`clipping` at or above 95% of the inverter maximum, else `normal`.",
    "inverter_temperature": (
        "Reading of the GivTCP inverter temperature entity, from the one stored at setup "
        "or found from the inverter serial."
    ),
    "inverter_temperature_status": (
        "Normal, Warm (60 °C or more), Derating (65 °C or more), Critical (75 °C or more) "
        "or Unknown."
    ),
    "current_rate": (
        "Unit import rate in force now. The `givtcp_rates_differ` and `givtcp_rate_differences` "
        "attributes compare the day, night and export rates GivTCP holds with the tariff "
        "entered here. See [Tariff](tariff.md#comparing-with-givtcps-rates). Absent when "
        "GivTCP's rates cannot be read."
    ),
    "current_rate_period": "Name of the active period, or the base rate name.",
    "live_grid_cost_rate": (
        "Cost per hour of the current grid flow. Positive when spending, negative when earning."
    ),
    "next_cheap_rate_start": (
        "Start time (HH:MM) of the next period cheaper than the base rate, or Now. "
        "The `summary` attribute adds the wait, such as `23:00 (in 8 h 56 min)`, or the time "
        "until cheap rates end, such as `Now (ends in 5 h 30 min)`. The end is that of the whole "
        "run of periods cheaper than the base rate, so a cheaper period inside a longer one does "
        "not cut it short. Absent on a tariff with no cheap period."
    ),
    "hours_to_cheap_rate": (
        "Hours until a period cheaper than the base rate starts. 0 while one is active."
    ),
    "cheapest_rate": "Lowest rate across the base rate and all periods.",
    "cheapest_rate_period": "Name of the cheapest rate.",
    "is_on_cheapest_rate": "yes when the current rate is the cheapest and a timed period exists.",
    "is_on_base_rate": "yes when no timed period is active.",
    "minutes_remaining_in_period": (
        "Minutes until the active timed period ends. Empty on the base rate."
    ),
    "rate_savings_vs_daytime": "Base rate minus current rate, floored at 0.",
    "avg_import_rate_today": "Import cost divided by imported kWh. Empty when nothing imported.",
    "avg_import_rate_this_week": "Import cost divided by imported kWh this week.",
    "avg_import_rate_this_month": "Import cost divided by imported kWh this month.",
    "solar_today": "Solar generated. Uses the GivTCP daily counter when present.",
    "import_today": "Grid import. Uses the GivTCP daily counter when present.",
    "grid_to_battery_today": (
        "Part of Grid Import Today that charged the battery. Uses GivTCP's AC charge counter. "
        "Unavailable when that counter is missing."
    ),
    "export_today": "Grid export. Uses the GivTCP daily counter when present.",
    "house_kwh_today": "House consumption. Uses the GivTCP load counter when present.",
    "zappi_today": "Energy delivered to the EV charger, from charger power.",
    "immersion_today": "Immersion energy, from the configured wattage while the switch is on.",
    "battery_charge_kwh_today": "Energy into the battery. Uses the GivTCP counter when present.",
    "battery_discharge_kwh_today": (
        "Energy out of the battery. Uses the GivTCP counter when present."
    ),
    "battery_throughput_kwh_today": "Battery energy in plus out.",
    "import_kwh_cheap_today": "Energy imported while a timed rate period was active.",
    "import_kwh_peak_today": (
        "Energy imported while no timed rate period was active, so at the base rate. "
        "With no timed rate period set, all import."
    ),
    "immersion_solar_kwh_today": "Solar energy that went to the immersion.",
    "self_consumed_kwh_today": "Solar generated minus exported, floored at 0.",
    "missed_solar_today": (
        "Export while the battery was at 99% or more and no EV or immersion load was on. "
        "Stays 0 until an immersion switch is set or an EV charger is found."
    ),
    "inverter_derating_today_minutes": "Minutes with the inverter at 65 °C or more.",
    "import_cost_today": "Import cost after the supplier discount and VAT.",
    "export_earnings_today": "Exported kWh times the export rate.",
    "zappi_cost_today": (
        "Import cost attributed to the EV charger, after the supplier discount and VAT. "
        "Standing charge and levy are not included, so it is higher than the EV energy "
        "times the bare rate by the discount and VAT factor."
    ),
    "house_cost_today": (
        "Import cost attributed to the rest of the house, after the supplier discount and VAT. "
        "Includes grid energy stored in the battery."
    ),
    "immersion_cost_today": (
        "Import cost attributed to the immersion, after the supplier discount and VAT."
    ),
    "import_cost_cheap_today": "Import cost while a timed rate period was active.",
    "import_cost_peak_today": (
        "Import cost while no timed rate period was active, so at the base rate. "
        "With no timed rate period set, all import cost."
    ),
    "immersion_savings_today": "Diverted solar kWh times (current rate minus export rate).",
    "saving_vs_grid_today": (
        "House load priced at the rate in force when it ran, minus net import cost "
        "(import cost minus export earnings)."
    ),
    "net_saving_today": "Saving vs Grid minus battery wear. Wear is 0 unless battery cost is set.",
    "net_position_today": "Export earnings minus import cost.",
    "self_sufficiency": (
        "Share of the house load, EV and immersion included, that did not come from the grid "
        "at the time. Grid energy stored in the battery is not counted against it. Attributes "
        "show the kWh behind the figure and the `basis`."
    ),
    "solar_share": (
        "Share of consumption met by solar generated and kept on site (generation minus export, "
        "battery storage included). Grid import and battery discharge do not count. "
        "0 with no consumption."
    ),
    "self_consumption": "Share of today's solar that was not exported. 0 with no solar.",
    "peak_import_fraction_today": (
        "Share of today's import that was at the base rate. 100 once anything is imported "
        "with no timed rate period set."
    ),
    "solar_capture_efficiency_today": "Solar generated minus missed solar, as a share of solar.",
    "battery_roundtrip_efficiency_today": (
        "Energy out of the battery divided by energy in. Unknown until at least 2 kWh has gone "
        "both in and out today, because earlier in the day the battery still holds energy "
        "charged overnight."
    ),
    "accrued_bill": (
        "Bill so far this period: energy less the supplier saving, standing charge and PSO levy, "
        "VAT, minus export earnings."
    ),
    "projected_bill": "Accrued bill spread over the whole bill period.",
    "days_remaining_in_period": "Days left in the bill period after today.",
    "days_in_period": "Day of the bill period, 1 on the bill start day.",
    "battery_cycles": (
        "Equivalent full cycles (capacity discharged once). The GivTCP BMS counter when it "
        "exists, otherwise falls in SoC divided by 100."
    ),
    "battery_remaining_life": "100 minus total cycles as a share of 6000 rated cycles.",
    "days_since_full_charge": "Days since the battery last reached 99% or more.",
    "battery_years_remaining": (
        "Rated cycles left divided by the average cycles per day. Empty for the first 7 days."
    ),
    "battery_usable_capacity_kwh": "Configured capacity times remaining life.",
    "battery_state": "Discharging, Full (99% or more), Charging or Idle.",
    "battery_cycle_cost_per_kwh": (
        "Battery cost divided by (2 x capacity x 6000). Empty when battery cost is 0."
    ),
    "battery_life_consumed_today": (
        "Today's throughput as a share of (2 x capacity x 6000 cycles)."
    ),
    "battery_throughput_budget_pct": (
        "Today's throughput as a share of the daily budget. Empty when the budget is 0."
    ),
    "battery_throughput_budget_status": "OK, High (80% or more) or Over budget.",
    "register_write_count": (
        "Lifetime writes sent to GivTCP. Saved and kept across restarts. The `recent_writes` "
        "attribute lists the latest writes and outside changes to the charge target and window."
    ),
    "overnight_charge_target": (
        "Tonight's target after overrides and the configured cap. Holds its value until the "
        "calculated target moves 5 points or more, and for an hour after it last changed. A move "
        "of 15 points or more shows at once."
    ),
    "overnight_charge_reason": (
        "Why that target was chosen. Changes only when the target does, and never says skipping "
        "while a charge is running. Attributes report the "
        "forecast accuracy correction: `accuracy_status` (for example `Waiting for data: 3 of 5 "
        "days`), `accuracy_applied`, `accuracy_measured_factor`, `accuracy_applied_factor`, "
        "`accuracy_usable_days`, `accuracy_days_needed` and `accuracy_days_stored`."
    ),
    "overnight_charge_window": (
        "The charge window written to slot 1, sized to the plan. The end holds until the plan "
        "moves it 15 minutes or more and the shown end has stood for an hour, or 45 minutes or "
        "more at once. Attributes: `window_start`, `window_end`, `window_extended`, "
        "`expected_kwh` and `expected_finish`."
    ),
    "overnight_charge_cost": "kWh to charge times the cheapest rate, before discount and VAT.",
    "estimated_soc_at_sunrise": (
        "Projected SoC when solar starts, taken as 08:00. While solar is generating "
        "it covers tonight's 8 hour pre-solar window from the current SoC."
    ),
    "night_survival_reason": (
        "Whether the battery should last until 08:00, with any shortfall. "
        "The charge plan does not skip a night this sensor calls Critical."
    ),
    "night_survival_confidence": (
        "Safe, Warning (within 5 points of minimum SoC) or Critical. "
        "The attributes say why and give the numbers."
    ),
    "cheap_rate_floor_status": "State of the cheap rate floor top-up, or Inactive.",
    "immersion_divert_reason": "Why the immersion is on or off.",
    "immersion_water_temperature": (
        "Reading of the immersion temperature sensor you set. Also lets a stored dashboard "
        "show the water temperature as soon as a sensor is set."
    ),
    "water_heating_cheapest_source": (
        "The cheapest way to heat the water now: `electricity`, `solar` or `oil`. Compares the "
        "cost of a kWh of heat from the grid (after discount and VAT), from solar surplus (the "
        "export rate) and from oil (the price of a litre over 85% of 10.35 kWh). Advice only: "
        "the integration does not control the oil boiler. The `suggestion` attribute is a "
        "sentence saying what to do and until when. Other attributes: `oil_cost_per_kwh`, "
        "`electricity_cost_per_kwh`, `cheapest_electricity_cost_per_kwh` (to the next ready time "
        "or 24 hours), `oil_saving_per_kwh` (negative when oil is dearer), `best_hours_for_oil`, "
        "`horizon`, `horizon_ends` and `cheapest_source_in_horizon`. Unavailable while the price "
        "cannot be read."
    ),
    "ev_charger_state": (
        "disconnected, connected, charging, paused, boosting, completed or unknown. "
        "Charging and boosting need the charger to be drawing power."
    ),
    "ev_power": "EV charger power.",
    "ev_session_energy": "Energy of the current session, as reported by the charger.",
    "ev_km_charged_today": "EV energy today divided by car efficiency. Empty with no EV energy.",
    "ev_cost_per_km_today": "EV cost today divided by km charged.",
    "ev_draining_battery": (
        "yes while the charger is charging, drawing power, and the battery discharges over 200 W."
    ),
    "ev_protection_reason": "Reason for the latest EV charge mode decision.",
    "ev_charging_source": "Not charging, Solar, Grid, Battery or Mixed.",
    "ev_solar_surplus_available": "Available when net solar surplus is 1380 W or more.",
    "solar_forecast_kwh_today": (
        "The charge plan's forecast for today, blended toward the pessimistic estimate and"
        " scaled by the accuracy correction. Not the provider's figure."
    ),
    "solar_forecast_raw_today": (
        "The forecast provider's own figure for today, as it stood just before midnight."
        " Empty when none was seen then."
    ),
    "solar_actual_vs_forecast_pct": (
        "Solar generated today as a share of the provider's forecast for today"
        " (Solar forecast today (provider)). Empty without one."
    ),
    "yesterday_forecast_accuracy_pct": (
        "Yesterday's actual solar as a share of the forecast for that day."
        " A day that beats the forecast reads above 100, with no upper limit."
    ),
    "forecast_accuracy_7day_avg_pct": "Average of the last 7 daily accuracy values.",
    "carbon_intensity": "Value of the carbon intensity entity you set.",
    "carbon_intensity_status": "Low (under 200), Medium (under 400) or High, in g CO2/kWh.",
    "today_summary": "Solar, import cost, immersion savings and self-sufficiency for today.",
    "charge_plan": "Tonight's target, the percentage to add and the cost, or Skip charge.",
    "week_summary": "Solar, import cost and self-sufficiency for this week.",
    "dry_run_active": "True when dry run mode is on.",
    "dry_run_last_skipped": "The last action dry run mode held back.",
    "integration_version": "Installed integration version.",
}


# What a sensor needs in order to exist, from `requires=` in its description.
REQUIRES_NOTES: dict[str, str] = {
    "EV_CHARGER": "Created only with an EV charger.",
    "IMMERSION_SWITCH": "Created only with an immersion switch.",
    "IMMERSION_SENSOR": "Created only with an immersion temperature sensor.",
    "IMMERSION_THERMOSTAT": "Created only with an immersion switch and temperature sensor.",
    "OIL_ADVICE": "Created only with an oil price and an immersion switch.",
}

RETIRED_SENSORS: tuple[tuple[str, str], ...] = (
    ("pre_boost_export_recommended", "Pre-boost export recommended"),
    ("pre_boost_export_kwh", "Pre-boost exportable kWh"),
    ("pre_boost_export_net_gain", "Pre-boost export net gain"),
)
# (key, name before, name now). The key and the entity ID of an existing install do not change.
RENAMED_SENSORS: tuple[tuple[str, str, str], ...] = (
    ("import_kwh_peak_today", "Import at peak rate", "Import at base rate"),
    ("import_kwh_peak_yesterday", "Import at peak rate yesterday", "Import at base rate yesterday"),
    ("import_kwh_peak_this_week", "Import at peak rate this week", "Import at base rate this week"),
    (
        "import_kwh_peak_this_month",
        "Import at peak rate this month",
        "Import at base rate this month",
    ),
    ("import_cost_peak_today", "Import cost at peak rate", "Import cost at base rate"),
    ("peak_import_fraction_today", "Peak rate import fraction", "Base rate import fraction"),
)
RENAMED_NOTE = (
    "These sensors were renamed because they measure the base rate, the rate that applies "
    "while no timed rate period is active. They are not a peak band, and no peak band is "
    "configured. The key and the unique ID did not change, so history, statistics and "
    "automations carry on. An install made before the rename keeps its old entity IDs, "
    "which still contain `peak`. A new install builds entity IDs from the new names."
)
RETIRED_NOTE = (
    "These sensors were removed. The integration never writes or advises forced battery "
    "export, and the gain figure was wrong. Setup deletes their entries from the entity "
    "registry. A dashboard card or automation that still uses one shows `unavailable` or "
    "`unknown` until you remove the reference."
)


def _attr(node: ast.expr | None) -> str:
    """Return the last name of a Name or Attribute node, or the constant's text."""
    if node is None:
        return ""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return "" if node.value is None else str(node.value)
    return ast.unparse(node)


def _literal(node: ast.expr | None, default):
    """Return a literal value from the node, or *default* when the node is absent."""
    if node is None:
        return default
    return ast.literal_eval(node)


def description_files() -> list[Path]:
    """Return the theme modules in the order sensor_descriptions/__init__.py joins them."""
    tree = ast.parse((DESCRIPTIONS_DIR / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == TABLE_NAME:
            return [DESCRIPTIONS_DIR / f"{part.value.value.id}.py" for part in node.value.elts]
    raise SystemExit(f"{TABLE_NAME} not found in sensor_descriptions/__init__.py")


def _description_calls(path: Path) -> list[ast.Call]:
    """Return the description constructor calls of one module, in source order."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == DESCRIPTION_CLASS
    ]
    return sorted(calls, key=lambda n: n.lineno)


def load_sensors() -> list[dict]:
    """Read every sensor description from sensor_descriptions/, in table order."""
    names = json.loads(EN_JSON.read_text(encoding="utf-8"))["entity"]["sensor"]
    calls = [call for path in description_files() for call in _description_calls(path)]
    sensors = []
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        key = ast.literal_eval(kw["key"])
        tkey = _literal(kw.get("translation_key"), key)
        name = names.get(tkey, {}).get("name") or _literal(kw.get("name"), key)
        unit_node = kw.get("native_unit_of_measurement")
        unit = UNITS.get(_attr(unit_node), _attr(unit_node))
        state_class = _attr(kw.get("state_class")).lower() or "none"
        reset_period = _literal(kw.get("reset_period"), None) or (
            "day" if _literal(kw.get("is_daily_total"), False) else None
        )
        available_fn = kw.get("available_fn")
        sensors.append(
            {
                "key": key,
                "name": name,
                "unit": unit,
                "device_class": _attr(kw.get("device_class")).lower(),
                "state_class": state_class,
                "enabled": bool(_literal(kw.get("entity_registry_enabled_default"), True)),
                "last_reset": reset_period if state_class == "total" else None,
                "diagnostic": _attr(kw.get("entity_category")) == "DIAGNOSTIC",
                "requires": _attr(kw.get("requires")),
                "needs_ev": (
                    available_fn is not None and "ev_available" in ast.unparse(available_fn)
                ),
            }
        )
    return sensors


def group_of(key: str) -> str:
    """Return the group heading for a sensor key."""
    if key in KEY_GROUPS:
        return KEY_GROUPS[key]
    for suffix, group in SUFFIX_GROUPS:
        if key.endswith(suffix):
            return group
    return "Other"


def _cell(value: str) -> str:
    return value if value else "-"


def _row(sensor: dict) -> str:
    notes = []
    if sensor["requires"]:
        notes.append(REQUIRES_NOTES[sensor["requires"]])
    if sensor["needs_ev"]:
        notes.append("EV charger needed.")
    if sensor["diagnostic"]:
        notes.append("Diagnostic category.")
    text = " ".join([DESCRIPTIONS.get(sensor["key"], ""), *notes]).strip()
    cells = [
        sensor["name"],
        f"`{sensor['key']}`",
        _cell(sensor["unit"]),
        _cell(sensor["device_class"]),
        sensor["state_class"],
        sensor["last_reset"] or "no",
        "yes" if sensor["enabled"] else "no",
        _cell(text),
    ]
    return "| " + " | ".join(cells) + " |"


def _renamed_section() -> list[str]:
    """The table of sensors whose display name changed."""
    rows = [f"| `{key}` | {old} | {new} |" for key, old, new in RENAMED_SENSORS]
    return [
        "## Renamed sensors",
        "",
        RENAMED_NOTE,
        "",
        "| Key | Previous name | Name now |",
        "|---|---|---|",
        *rows,
        "",
    ]


def _retired_section() -> list[str]:
    """The table of sensors the integration no longer creates."""
    rows = [f"| {name} | `{key}` |" for key, name in RETIRED_SENSORS]
    return ["## Removed sensors", "", RETIRED_NOTE, "", "| Sensor | Key |", "|---|---|", *rows, ""]


def generate() -> str:
    """Return the full text of docs/sensors.md."""
    sensors = load_sensors()
    enabled = sum(1 for s in sensors if s["enabled"])
    by_group: dict[str, list[dict]] = {g: [] for g in GROUPS}
    for sensor in sensors:
        by_group[group_of(sensor["key"])].append(sensor)

    lines = [
        "<!-- Generated by scripts/gen_sensor_docs.py from sensor.py. Do not edit by hand. -->",
        "",
        "# Sensors",
        "",
        f"The integration creates {len(sensors)} sensors. {enabled} are enabled by default and "
        f"{len(sensors) - enabled} are disabled. Enable a disabled sensor in "
        "**Settings > Devices & Services > GivEnergy Inverter Manager > entities**.",
        "",
        "This page is generated from the code. Run `python scripts/gen_sensor_docs.py` after "
        "changing `sensor.py`. For switches, numbers and the button, see "
        "[Entities](entities.md).",
        "",
        "Column guide:",
        "",
        "- **Key**: the suffix of the sensor's unique ID. It does not set the entity ID. "
        "Home Assistant builds the entity ID from the device name and the sensor name, for "
        "example `sensor.givenergy_inverter_manager_solar_power`. Check yours in "
        "**Settings > Entities**.",
        "- **Unit**: `currency` is the symbol of the currency chosen in the tariff.",
        "- **Last reset**: `day`, `week`, `month` or `year` means the sensor reports "
        "`last_reset` as the start of that period. `no` means it reports none. See "
        "[Long-term statistics](long-term-statistics.md).",
        "- **Enabled**: whether the sensor is enabled when first created.",
        "",
        "A sensor marked `Created only with ...` exists only while that device is present: an "
        "EV charger the integration discovered, the immersion switch, or the immersion "
        "temperature sensor. An install without the device has no such sensor, so nothing "
        "sits unavailable. The sensor appears by itself when the device appears: when "
        "discovery first finds an EV charger, or after an options change that sets the "
        "immersion entities (the entry reloads). The registry entries of a device that is "
        "gone are removed when the entry next loads. An EV charger's are kept while Home "
        "Assistant is starting, because its own integration may not have loaded yet. A "
        "dashboard made by the integration follows these changes. See "
        "[Dashboard](dashboard.md#devices-you-add-or-remove-later).",
        "",
    ]
    for group, members in by_group.items():
        if not members:
            continue
        lines += [f"## {group}", ""]
        if GROUPS[group]:
            lines += [GROUPS[group], ""]
        lines += [
            "| Sensor | Key | Unit | Device class | State class | Last reset | Enabled | "
            "What it reports |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += [_row(s) for s in members]
        lines.append("")
    lines += _renamed_section()
    lines += _retired_section()
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/sensors.md is stale")
    parser.add_argument("--stdout", action="store_true", help="print the page instead of writing")
    args = parser.parse_args(argv)

    text = generate()
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            sys.stderr.write("docs/sensors.md is out of date. Run scripts/gen_sensor_docs.py\n")
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
