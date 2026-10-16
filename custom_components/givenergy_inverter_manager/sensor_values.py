"""
sensor_values.py — Pure value functions behind the sensor descriptions.

Each function takes a CoordinatorData snapshot (or one of its energy accumulators) and
returns the value a sensor reports. Nothing here imports Home Assistant, so every
rule can be unit tested directly. The sensor_descriptions package holds the description
table and references these functions by name.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import (
    BATTERY_EFFICIENCY_MIN_KWH,
    BATTERY_FULL_SOC_PCT,
    BATTERY_RATED_CYCLES,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
    POWER_DIRECTION_BAND_W,
)
from .core.alt_heat_advice import WaterHeatingAdvice
from .core.alt_heat_schedule import AltHeatSchedule
from .core.battery import SurvivalReport, survival_attributes
from .core.engine import CoordinatorData
from .core.ev_session import EVSession, EVSessionLog, recent_table
from .core.repair_summary import repairs_summary
from .core.setup_progress import setup_state
from .core.tariff import EnergyAccumulator
from .core.tomorrow_outlook import outlook_table
from .core.write_log import newest_first

GRID_IMPORTING = "Importing"
GRID_EXPORTING = "Exporting"
GRID_BALANCED = "Balanced"

BATTERY_CHARGING = "Charging"
BATTERY_DISCHARGING = "Discharging"
BATTERY_IDLE = "Idle"
BATTERY_FULL = "Full"

NIGHT_CRITICAL = "Critical"
NIGHT_WARNING = "Warning"
NIGHT_SAFE = "Safe"

RATE_NOW = "Now"

SUFFICIENCY_BASIS_AC_CHARGE = "ac_charge_counter"
SUFFICIENCY_BASIS_IMPORT_ONLY = "import_only"

YES = "yes"
NO = "no"


def _round_or_none(value: float | None, places: int) -> float | None:
    """Round a value, passing None through."""
    return None if value is None else round(value, places)


def _percentage(part: float, whole: float, places: int) -> float | None:
    """Return part as a percentage of whole, or None when whole is not positive."""
    if whole > 0:
        return round(part / whole * 100, places)
    return None


# ── Power and grid ───────────────────────────────────────────────────────────


def grid_power_direction(data: CoordinatorData) -> str:
    """Say whether the house is importing from, exporting to, or balanced with the grid."""
    if data.grid_power_w > POWER_DIRECTION_BAND_W:
        return GRID_IMPORTING
    if data.grid_power_w < -POWER_DIRECTION_BAND_W:
        return GRID_EXPORTING
    return GRID_BALANCED


def solar_power_pct_of_max(data: CoordinatorData) -> float | None:
    """Return solar output as a percentage of the inverter limit, None without a limit."""
    return _percentage(data.solar_power_w, data.inverter_max_w, 1)


# ── Battery ──────────────────────────────────────────────────────────────────


def battery_power_direction(data: CoordinatorData) -> str:
    """Say whether the battery is charging, discharging or idle, ignoring small flows."""
    if data.battery_power_w > POWER_DIRECTION_BAND_W:
        return BATTERY_CHARGING
    if data.battery_power_w < -POWER_DIRECTION_BAND_W:
        return BATTERY_DISCHARGING
    return BATTERY_IDLE


def battery_state(data: CoordinatorData) -> str:
    """Return Discharging, Full, Charging or Idle. Discharging wins over Full."""
    direction = battery_power_direction(data)
    if direction == BATTERY_DISCHARGING:
        return direction
    if data.battery_soc >= BATTERY_FULL_SOC_PCT:
        return BATTERY_FULL
    return direction


def battery_kwh_available(data: CoordinatorData) -> float | None:
    """Return the energy held in the battery now, None when the capacity is unknown."""
    if data.battery_capacity_kwh > 0:
        return round(data.battery_soc / 100 * data.battery_capacity_kwh, 2)
    return None


def battery_usable_capacity_kwh(data: CoordinatorData) -> float | None:
    """Return the capacity left after wear, None when the capacity is unknown."""
    if data.battery_capacity_kwh > 0:
        remaining_pct = data.battery_stats.estimated_remaining_life_pct
        return round(data.battery_capacity_kwh * remaining_pct / 100, 2)
    return None


def battery_life_consumed_today_pct(data: CoordinatorData) -> float:
    """Return the share of rated battery life used today.

    One rated cycle is a full charge plus a full discharge, so it takes
    2 x capacity of throughput.
    """
    capacity = data.battery_capacity_kwh
    if capacity > 0:
        throughput = data.today.battery_throughput_kwh
        return round(throughput / (2 * capacity * BATTERY_RATED_CYCLES) * 100, 6)
    return 0.0


def battery_cycle_cost_per_kwh(data: CoordinatorData) -> float | None:
    """Return the wear cost of each kWh of battery throughput, None when it is zero."""
    cost = data.battery_cycle_cost_per_kwh
    return round(cost, 5) if cost else None


def battery_years_remaining(data: CoordinatorData) -> float | None:
    """Return the estimated years of battery life left, None until it can be estimated."""
    return _round_or_none(data.battery_years_remaining, 1)


def battery_throughput_budget_pct(data: CoordinatorData) -> float | None:
    """Return the share of the throughput budget used, None when no budget applies."""
    return _round_or_none(data.battery_throughput_budget_pct, 1)


def battery_roundtrip_efficiency_today(data: CoordinatorData) -> float | None:
    """Return today's discharge as a percentage of charge, None until enough has moved.

    Early in the day the battery still holds energy charged overnight, so a small
    discharge over a large charge reads far below the real efficiency. The figure
    stays unknown until both directions reach BATTERY_EFFICIENCY_MIN_KWH.
    """
    charge = data.today.battery_charge_kwh
    discharge = data.today.battery_discharge_kwh
    if min(charge, discharge) < BATTERY_EFFICIENCY_MIN_KWH:
        return None
    return _percentage(discharge, charge, 1)


# ── Tariff ───────────────────────────────────────────────────────────────────


def next_cheap_rate_start(data: CoordinatorData) -> str | None:
    """Return when the next cheap rate starts, "Now" while one is active, else None."""
    if data.next_cheap_rate_start is not None:
        return data.next_cheap_rate_start
    return RATE_NOW if data.hours_to_cheap_rate == 0.0 else None


def _duration_text(minutes: float) -> str:
    """Return a duration in whole minutes as "45 min", "9 h" or "8 h 56 min"."""
    hours, rest = divmod(round(minutes), 60)
    parts = ([f"{hours} h"] if hours else []) + ([f"{rest} min"] if rest or not hours else [])
    return " ".join(parts)


def cheap_rate_summary(data: CoordinatorData) -> str | None:
    """Return "23:00 (in 8 h 56 min)", "Now (ends in 5 h 30 min)", or None without a cheap rate."""
    start = next_cheap_rate_start(data)
    if start is None:
        return None
    if start == RATE_NOW:
        return _now_summary(data.cheap_run_remaining_minutes)
    if data.hours_to_cheap_rate is None:
        return start
    return f"{start} (in {_duration_text(data.hours_to_cheap_rate * 60)})"


def _now_summary(minutes_remaining: float | None) -> str:
    """Return "Now", with how long the cheap run has left when that is known."""
    if minutes_remaining is None:
        return RATE_NOW
    return f"{RATE_NOW} (ends in {_duration_text(minutes_remaining)})"


def cheap_rate_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the summary attribute a dashboard tile shows, None on a tariff without one."""
    summary = cheap_rate_summary(data)
    return None if summary is None else {"summary": summary}


def dry_run_attributes(data: CoordinatorData) -> dict[str, Any]:
    """Return the summary attribute a dashboard tile shows: On or Off, not True or False.

    A test instance adds a flag the dashboard banner reads. It is absent on any other install.
    """
    attributes: dict[str, Any] = {"summary": "On" if data.dry_run else "Off"}
    if data.test_instance:
        attributes["test_instance"] = True
    return attributes


def setup_progress_state(data: CoordinatorData) -> str:
    """complete once every required checklist item is done, incomplete before that."""
    return setup_state(data.setup_items)


def setup_progress_attributes(data: CoordinatorData) -> dict[str, Any]:
    """The checklist the dashboard card draws, one entry per item, required items first."""
    return {"items": [item.as_dict() for item in data.setup_items]}


def immersion_ready_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the next hot water ready time, whether it will be met and the rate behind it."""
    if data.immersion_ready_time is None:
        return None
    return {
        "ready_by": f"{data.immersion_ready_time:%H:%M}",
        "expected_ready": data.immersion_expected_ready,
        "heating_rate_c_per_h": data.immersion_heating_rate_c_per_h,
        "heating_rate_source": data.immersion_rate_source,
    }


def immersion_water_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """The ready-by attributes and the planned heating sentence, None while neither is set."""
    attributes = immersion_ready_attributes(data) or {}
    if data.immersion_planned_heating is not None:
        attributes = {**attributes, "planned_heating": data.immersion_planned_heating}
    return attributes or None


def water_heating_source(data: CoordinatorData) -> str | None:
    """Return the cheapest source to heat the water now, None without advice."""
    advice = data.water_heating_advice
    return None if advice is None else advice.source


def _alt_start_attributes(advice: WaterHeatingAdvice) -> dict[str, Any]:
    """The start for the next ready time. Absent unless the alternative should be started."""
    start = advice.alt_start
    if start is None or start.start_by is None:
        return {}
    return {
        "alt_start_by": f"{start.start_by:%H:%M}",
        "alt_run_minutes": start.run_minutes,
        "alt_for_ready_time": f"{start.ready_at:%H:%M}",
    }


def _alt_schedule_attributes(schedule: AltHeatSchedule | None) -> dict[str, Any]:
    """The suggested alternative heating schedule. Absent until the record holds a week of days.

    From then on the list and the days are always there, and the list is empty when nothing is
    worth suggesting. The sentence is only there with a suggestion. None of this is in the
    suggestion attribute, which stays the live advice.
    """
    if schedule is None:
        return {}
    attributes: dict[str, Any] = {
        "alt_schedule": list(schedule.windows),
        "alt_schedule_saving": round(schedule.saving, 2),
        "alt_schedule_days": schedule.days,
    }
    if schedule.sentence is not None:
        attributes["alt_schedule_suggestion"] = schedule.sentence
    return attributes


def water_heating_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the suggestion and the costs per kWh of heat behind it, None without advice."""
    advice = data.water_heating_advice
    if advice is None:
        return None
    attributes = {
        "suggestion": advice.suggestion,
        "alt_label": advice.label,
        "alt_cost_per_kwh": round(advice.alt_cost_per_kwh, 4),
        "electricity_cost_per_kwh": round(advice.electricity_cost_per_kwh, 4),
        "cheapest_electricity_cost_per_kwh": round(advice.cheapest_electricity_cost_per_kwh, 4),
        "alt_saving_per_kwh": round(advice.alt_saving_per_kwh, 4),
        "best_hours_for_alt": list(advice.alt_hours),
        "horizon": advice.horizon,
        "horizon_ends": advice.horizon_ends,
        "cheapest_source_in_horizon": advice.cheapest_source_in_horizon,
        **_alt_start_attributes(advice),
        **_alt_schedule_attributes(data.alt_heat_schedule),
    }
    if advice.keep_warm is not None:
        attributes["alt_keep_warm"] = advice.keep_warm
    return attributes


def charge_target_conflict_state(data: CoordinatorData) -> str:
    """none or suspected: whether something else seems to be setting the charge target."""
    return data.charge_target_conflict.state


def charge_target_conflict_attributes(data: CoordinatorData) -> dict[str, Any]:
    """How many outside changes the suspicion rests on, the newest, and the entity it is about."""
    status = data.charge_target_conflict
    return {
        "changes": status.count,
        "last_seen": status.last_seen_iso,
        "target_entity": status.entity_id,
    }


def average_import_rate(accumulator: EnergyAccumulator) -> float | None:
    """Return the average price paid per imported kWh, None when nothing was imported."""
    if accumulator.import_kwh > 0:
        return round(accumulator.total_import_cost / accumulator.import_kwh, 4)
    return None


def cheap_import_percentage(accumulator: EnergyAccumulator) -> float | None:
    """Return the share of imported energy bought at a cheap rate, None without imports."""
    if accumulator.import_kwh > 0:
        return round(accumulator.cheap_import_fraction * 100, 1)
    return None


# ── Overnight charge and night survival ──────────────────────────────────────


def overnight_charge_target(data: CoordinatorData) -> int | None:
    """Return the published recommended target, None before the first decision."""
    if data.published_charge_decision:
        return data.published_charge_decision.target_soc
    return None


def overnight_charge_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Whether the published target is a charge goal or the level held on a skipped night."""
    decision = data.published_charge_decision
    if decision is None:
        return None
    return {"plan": "skip" if decision.skip_charge else "charge"}


def overnight_charge_reason(data: CoordinatorData) -> str | None:
    """Return why the published target was recommended, None before the first decision."""
    if data.published_charge_decision:
        reason = data.published_charge_decision.reason
        return f"{data.charge_replan_note} {reason}" if data.charge_replan_note else reason
    return None


def forecast_accuracy_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the measured accuracy factor and its usable days, None before the first cycle."""
    accuracy = data.forecast_accuracy
    if accuracy is None:
        return None
    return {
        "accuracy_status": accuracy.status,
        "accuracy_applied": accuracy.applied,
        "accuracy_measured_factor": _round_or_none(accuracy.measured_factor, 2),
        "accuracy_applied_factor": _round_or_none(accuracy.applied_factor, 2),
        "accuracy_usable_days": accuracy.usable_days,
        "accuracy_days_needed": accuracy.days_needed,
        "accuracy_days_stored": accuracy.days_stored,
    }


def overnight_charge_cost(data: CoordinatorData) -> float | None:
    """Return the cost of tonight's planned charge, None before the first decision."""
    if data.published_charge_decision:
        return round(data.published_charge_decision.cost_to_charge, 3)
    return None


def tomorrow_outlook_cost(data: CoordinatorData) -> float | None:
    """The projected net cost of the solar day the plan is for, None without a projection."""
    return data.tomorrow_outlook.net_cost if data.tomorrow_outlook else None


def tomorrow_outlook_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """The lines behind the projected cost, and the dashboard's table of them."""
    outlook = data.tomorrow_outlook
    if outlook is None:
        return None
    return {
        "day": outlook.on.isoformat(),
        "import_kwh": round(outlook.import_kwh, 2),
        "export_kwh": round(outlook.export_kwh, 2),
        "import_cost": outlook.import_cost,
        "export_credit": outlook.export_credit,
        "charge_kwh": round(outlook.charge_kwh, 2),
        "charge_cost": outlook.charge_cost,
        "net_cost": outlook.net_cost,
        "end_soc_pct": round(outlook.end_soc_pct, 1),
        "min_soc_pct": round(outlook.min_soc_pct, 1),
        "forecast_kwh": round(outlook.forecast_kwh, 2),
        "basis": outlook.basis,
        "table": outlook_table(outlook, data.currency_symbol),
    }


def overnight_charge_window(data: CoordinatorData) -> str | None:
    """Return the charge window to write, for example "02:00 to 06:30", None before a decision."""
    return data.published_charge_window.text if data.published_charge_window else None


def overnight_charge_window_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return what the window is sized for, None when there is no window."""
    window = data.published_charge_window
    if window is None:
        return None
    finish = window.finish_time
    return {
        "window_start": window.start.strftime("%H:%M"),
        "window_end": window.end.strftime("%H:%M"),
        "window_extended": window.extended,
        "expected_kwh": window.expected_kwh,
        "expected_finish": finish.strftime("%H:%M") if finish else None,
    }


def night_survival_confidence(data: CoordinatorData) -> str | None:
    """Return Critical, Warning or Safe for tonight, None before the first cycle.

    Warning means the battery lasts but ends within the warning margin of the minimum SoC.
    """
    if not data.survival_reason:
        return None
    if not data.will_survive_night:
        return NIGHT_CRITICAL
    if data.estimated_soc_at_sunrise < data.battery_min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT:
        return NIGHT_WARNING
    return NIGHT_SAFE


def _planned_charge_soc(data: CoordinatorData) -> float | None:
    """The SoC at sunrise with tonight's planned charge, None while no charge counts."""
    projection = data.sunrise_with_charge
    if projection is None or not projection.charge_counts:
        return None
    return projection.soc


def night_survival_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the attributes that explain the night survival level, None before a cycle.

    The level is judged without a charge. The words also give the figure with tonight's
    planned charge while one counts.
    """
    if not data.survival_reason:
        return None
    return survival_attributes(
        SurvivalReport(
            data.will_survive_night,
            data.estimated_soc_at_sunrise,
            data.battery_min_soc,
            data.battery_soc,
            data.survival_reason,
            _planned_charge_soc(data),
            data.battery_pause,
        )
    )


def sunrise_with_charge_soc(data: CoordinatorData) -> float | None:
    """Return the SoC at sunrise with tonight's planned charge, None before the first cycle."""
    projection = data.sunrise_with_charge
    return None if projection is None else round(projection.soc, 1)


def sunrise_with_charge_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return what the figure is made of, None before the first cycle.

    soc_at_charge_start and charge_window are None on a night with no charge in the figure.
    """
    projection = data.sunrise_with_charge
    if projection is None:
        return None
    return {
        "soc_at_charge_start": _round_or_none(projection.soc_at_charge_start, 1),
        "charge_added_pct": round(projection.charge_added_pct, 1),
        "charge_window": projection.charge_window,
        "basis": projection.basis,
    }


def register_write_attributes(data: CoordinatorData) -> dict[str, Any]:
    """The recent writes and outside changes to the charge entities, newest first."""
    return {"recent_writes": newest_first(data.register_write_log)}


# ── Savings ──────────────────────────────────────────────────────────────────


def saving_attributes(data: CoordinatorData) -> dict[str, Any]:
    """The part of the saving that is stored energy, so the figure can be checked by hand.

    stored_energy_change_kwh is None while the battery capacity is unknown, because the
    change in kWh cannot be worked out then and the value is 0.
    """
    known = data.battery_capacity_kwh > 0
    return {
        "stored_energy_value": round(data.stored_energy_value, 4),
        "stored_energy_change_kwh": round(data.stored_energy_change_kwh, 3) if known else None,
    }


# ── Self-sufficiency ─────────────────────────────────────────────────────────


def _sufficiency_basis(acc: EnergyAccumulator, data: CoordinatorData) -> str:
    """Say whether the grid-to-battery figure was measured, or all import counted as grid.

    The figure is measured when GivTCP's AC charge counter is readable now or the period
    already holds energy from it. Otherwise nothing can be subtracted from import.
    """
    if data.grid_to_battery_counter_available or acc.grid_to_battery_kwh > 0:
        return SUFFICIENCY_BASIS_AC_CHARGE
    return SUFFICIENCY_BASIS_IMPORT_ONLY


def _sufficiency_attributes(acc: EnergyAccumulator, data: CoordinatorData) -> dict[str, Any]:
    """Where the period's energy came from, so the percentage can be checked by hand."""
    return {
        "house_load_kwh": round(acc.house_kwh, 3),
        "from_grid_kwh": round(acc.grid_to_house_kwh, 3),
        "grid_to_battery_kwh": round(acc.grid_to_battery_kwh, 3),
        "from_solar_and_battery_kwh": round(acc.supplied_without_grid_kwh, 3),
        "basis": _sufficiency_basis(acc, data),
    }


def self_sufficiency_attributes_today(data: CoordinatorData) -> dict[str, Any]:
    return _sufficiency_attributes(data.today, data)


def self_sufficiency_attributes_yesterday(data: CoordinatorData) -> dict[str, Any]:
    return _sufficiency_attributes(data.yesterday, data)


def self_sufficiency_attributes_week(data: CoordinatorData) -> dict[str, Any]:
    return _sufficiency_attributes(data.week, data)


def self_sufficiency_attributes_month(data: CoordinatorData) -> dict[str, Any]:
    return _sufficiency_attributes(data.month, data)


# ── Inverter and carbon ──────────────────────────────────────────────────────


def inverter_temperature(data: CoordinatorData) -> float | None:
    """Return the inverter temperature in degrees Celsius, None when not configured."""
    return _round_or_none(data.inverter_temperature, 1)


def carbon_intensity(data: CoordinatorData) -> float | None:
    """Return the grid carbon intensity in g CO2/kWh, None when not configured."""
    return _round_or_none(data.carbon_intensity_gco2, 1)


def carbon_intensity_status(data: CoordinatorData) -> str | None:
    """Return the carbon intensity band, None when the intensity is unknown."""
    if data.carbon_intensity_gco2 is not None:
        return data.carbon_intensity_status
    return None


# ── Solar ────────────────────────────────────────────────────────────────────


def solar_capture_efficiency_today(data: CoordinatorData) -> float | None:
    """Return the share of today's solar that was not curtailed, None without solar."""
    captured = max(0.0, data.today.solar_kwh - data.today.missed_solar_kwh)
    return _percentage(captured, data.today.solar_kwh, 1)


def solar_forecast_raw_today(data: CoordinatorData) -> float | None:
    """Return the provider's own forecast for today, None when none was seen before midnight."""
    return _round_or_none(data.solar_forecast_raw_kwh_today, 3)


def solar_forecast_attributes(data: CoordinatorData) -> dict[str, Any]:
    """Say which solar profile the charge plan spread the forecast with.

    `forecast` when it used the forecast provider's own per-period shape, `standard curve` for
    the bell curve centred on 13:00 (a provider with no shape, or a night the plan did not
    simulate).
    """
    return {"solar_profile_source": "forecast" if data.solar_shape_used else "standard curve"}


def solar_actual_vs_forecast_pct(data: CoordinatorData) -> float | None:
    """Return today's solar as a percentage of the provider's forecast for today.

    The charge plan's own forecast is blended toward the pessimistic estimate and scaled by
    the accuracy correction, so it is not the figure to judge the day against. None when no
    provider forecast was seen before midnight.
    """
    forecast = data.solar_forecast_raw_kwh_today
    if forecast is None:
        return None
    return _percentage(data.today.solar_kwh, forecast, 1)


def _ev_session_log(data: CoordinatorData) -> EVSessionLog:
    return data.ev_sessions if data.ev_sessions is not None else EVSessionLog()


def ev_session_cost(data: CoordinatorData) -> float | None:
    """The cost of the running EV session, else of the last one, None before the first."""
    session = _ev_session_log(data).latest
    return round(session.cost, 4) if session is not None else None


def _iso_or_none(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _session_row(session: EVSession) -> dict[str, Any]:
    return {
        "start": session.start.isoformat(),
        "end": _iso_or_none(session.end),
        "energy_kwh": round(session.energy_kwh, 3),
        "cost": round(session.cost, 4),
        "per_kwh": _round_or_none(session.per_kwh, 4),
        # The integration does not split the car's energy by source, so no solar share is known.
        "solar_kwh": None,
    }


def ev_session_attributes(data: CoordinatorData) -> dict[str, Any]:
    """The session the state shows, and the finished sessions newest first with their table."""
    log = _ev_session_log(data)
    session = log.latest
    return {
        "session_energy_kwh": round(session.energy_kwh, 3) if session is not None else None,
        "started": _iso_or_none(session.start if session is not None else None),
        "ended": _iso_or_none(session.end if session is not None else None),
        "recent_sessions": [_session_row(s) for s in log.recent],
        "recent_table": recent_table(log.recent, data.currency_symbol),
    }


def active_repairs_attributes(data: CoordinatorData) -> dict[str, Any]:
    """Each open repair of this integration, and the markdown summary the dashboard shows."""
    return {
        "issues": [issue.as_attribute() for issue in data.active_repairs],
        "summary": repairs_summary(data.active_repairs),
    }
