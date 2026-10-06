"""
rules.py — All decision logic for GivEnergy Inverter Manager.

Every function here is pure Python with no HA imports — fully unit-testable.

The algorithm parameters this module uses are documented named constants in const.py.
Nothing is hardcoded as a bare magic number.

Sections:
  monthly_solar_fractions()           — latitude-based seasonal solar estimate
  calculate_overnight_charge_target() — what SoC to charge to tonight
  should_divert_to_immersion()        — whether to run the immersion heater
  suggest_appliance_run()             — whether now is a good time for a high-load appliance
  decide_ev_charger_action()          — what mode the EV charger should be in
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..const import (
    APPLIANCE_MIN_BATTERY_SOC,
    APPLIANCE_RATE_THRESHOLD,
    CHARGE_EV_SOC_BONUS,
    CHARGE_FORECAST_CORRECTION_MAX,
    CHARGE_FORECAST_CORRECTION_MIN,
    CHARGE_FORECAST_CORRECTION_MIN_DAYS,
    CHARGE_FORECAST_CORRECTION_MIN_KWH,
    CHARGE_LOAD_PROFILE_MIN_COVERAGE,
    CHARGE_LOAD_PROFILE_MIN_DAYS,
    CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS,
    CHARGE_MIN_TARGET_HEADROOM_PCT,
    CHARGE_MORNING_LOAD_FRACTION,
    CHARGE_PEAK_SOLAR_HOURS,
    CHARGE_SHOULDER_MIN_SOC,
    CHARGE_SHOULDER_MONTHS,
    CHARGE_SKIP_HEADROOM,
    CHARGE_SOLAR_USABLE_FRACTION,
    CHARGE_STRONG_BUFFER,
    CHARGE_WINTER_MONTHS,
    CHARGE_WINTER_SKIP_SOC_PCT,
    CLIPPING_THRESHOLD_PERCENT,
    DEFAULT_CURRENCY_SYMBOL,
    EV_CHARGER_MIN_POWER_W,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from ..discovery.ev_charger import (
    ZAPPI_ECO_PLUS_MODE,
    EVCharger,
    EVChargerBrand,
)
from .battery import NightEstimateInputs, estimate_will_survive_night, hours_until_solar

# ── Seasonal solar fractions ──────────────────────────────────────────────────


def monthly_solar_fractions(latitude_deg: float) -> dict[int, float]:
    """
    Calculate relative monthly solar generation potential from latitude.

    Uses the Liu & Jordan extraterrestrial radiation formula — purely
    astronomical (day length × solar angle), no cloud-cover correction.
    Normalized so the peak month = 1.0.

    Called once at coordinator startup using hass.config.latitude.

    Examples:
      53°N (Ireland)  → Jun ~1.0, Dec ~0.14
      48°N (France)   → Jun ~1.0, Dec ~0.20
      37°N (Spain)    → Jun ~1.0, Dec ~0.41
      51°N (London)   → Jun ~1.0, Dec ~0.12
    """
    lat = math.radians(latitude_deg)
    # Mid-month representative day of year
    mid_doy = [17, 47, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344]

    raw: dict[int, float] = {}
    for month, doy in enumerate(mid_doy, 1):
        decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
        cos_ws = max(-1.0, min(1.0, -math.tan(lat) * math.tan(decl)))
        ws = math.acos(cos_ws)
        h0 = max(
            0.0,
            ws * math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.sin(ws),
        )
        raw[month] = h0

    peak = max(raw.values()) or 1.0
    return {m: round(v / peak, 3) for m, v in raw.items()}


# ── Overnight charge decision ─────────────────────────────────────────────────

def _make_solar_slot_weights() -> tuple[float, ...]:
    """Build normalized 48-slot (30-min) solar generation weights.

    Bell curve centred at 13:00 with σ=3.5 hours, active only between 06:30–19:30.
    Called once at module import; the result is stored in _SOLAR_SLOT_WEIGHTS.
    """
    raw = [
        math.exp(-0.5 * ((slot / 2.0 - 13.0) / 3.5) ** 2)
        if 6.5 <= slot / 2.0 <= 19.5
        else 0.0
        for slot in range(48)
    ]
    total = sum(raw)
    return tuple(w / total for w in raw) if total > 0 else (1 / 48,) * 48


# Normalized per-slot solar weights — built once, reused every cycle.
_SOLAR_SLOT_WEIGHTS: tuple[float, ...] = _make_solar_slot_weights()


_PROFILE_DAY_WEIGHTS = (1.0, 0.85, 0.7, 0.6, 0.5, 0.45, 0.4)


def build_load_profile(
    history: Sequence[dict[str, Any]],
    target_weekday: int,
) -> list[float] | None:
    """
    Build a 48-slot baseline load profile (kWh per 30 min) from stored daily records.

    Each record is {"date": ISO date, "slots": 48 kWh values, "coverage": 0-1}, oldest
    first. Records covering less than CHARGE_LOAD_PROFILE_MIN_COVERAGE of the day are
    skipped. Returns None when fewer than CHARGE_LOAD_PROFILE_MIN_DAYS complete days
    remain. When at least CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS complete days fall
    on target_weekday (Monday=0), only those are used. Newer days weigh more.
    """
    complete: list[tuple[int, list[float]]] = []
    for entry in history:
        try:
            slots = [float(v) for v in entry["slots"]]
            weekday = date.fromisoformat(entry["date"]).weekday()
            coverage = float(entry["coverage"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(slots) == 48 and coverage >= CHARGE_LOAD_PROFILE_MIN_COVERAGE:
            complete.append((weekday, slots))

    if len(complete) < CHARGE_LOAD_PROFILE_MIN_DAYS:
        return None

    same_weekday = [c for c in complete if c[0] == target_weekday]
    chosen = (
        same_weekday
        if len(same_weekday) >= CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS
        else complete
    )
    newest_first = list(reversed(chosen))[: len(_PROFILE_DAY_WEIGHTS)]
    total_weight = sum(_PROFILE_DAY_WEIGHTS[: len(newest_first)])
    return [
        sum(slots[i] * _PROFILE_DAY_WEIGHTS[n] for n, (_, slots) in enumerate(newest_first))
        / total_weight
        for i in range(48)
    ]


def forecast_correction_factor(records: Sequence[dict[str, Any]]) -> float | None:
    """
    Median actual/forecast ratio from recent {"forecast", "actual", "clipped"} records.

    Days where the forecast or actual is under CHARGE_FORECAST_CORRECTION_MIN_KWH, or
    where the inverter was clipping, are ignored. Returns None with fewer than
    CHARGE_FORECAST_CORRECTION_MIN_DAYS usable days, otherwise the median clamped to
    CHARGE_FORECAST_CORRECTION_MIN..MAX.
    """
    ratios: list[float] = []
    for record in records:
        try:
            forecast = float(record["forecast"])
            actual = float(record["actual"])
            clipped = bool(record.get("clipped", False))
        except (KeyError, TypeError, ValueError):
            continue
        if clipped:
            continue
        if (
            forecast < CHARGE_FORECAST_CORRECTION_MIN_KWH
            or actual < CHARGE_FORECAST_CORRECTION_MIN_KWH
        ):
            continue
        ratios.append(actual / forecast)
    if len(ratios) < CHARGE_FORECAST_CORRECTION_MIN_DAYS:
        return None
    return max(
        CHARGE_FORECAST_CORRECTION_MIN,
        min(CHARGE_FORECAST_CORRECTION_MAX, statistics.median(ratios)),
    )


def _profile_usable(load_profile: list[float] | None) -> bool:
    return (
        load_profile is not None
        and len(load_profile) == 48
        and min(load_profile) >= 0
        and sum(load_profile) > 0
    )


def _slot_loads_kwh(avg_daily_kwh: float, load_profile: list[float] | None) -> list[float]:
    """Per-slot load for the simulation: the profile scaled to avg_daily_kwh, else flat."""
    if load_profile is not None and _profile_usable(load_profile):
        scale = avg_daily_kwh / sum(load_profile)
        return [v * scale for v in load_profile]
    return [avg_daily_kwh / 48] * 48


@dataclass(frozen=True)
class _SimulatedDay:
    """One day to simulate: the solar forecast, the battery size and the load per slot."""

    forecast_kwh: float
    battery_capacity_kwh: float
    slot_loads_kwh: list[float]


def _simulate_min_soc(start_soc_pct: float, day: _SimulatedDay) -> float:
    """Simulate one day starting from start_soc_pct. Return the minimum SoC reached."""
    soc_pct = start_soc_pct
    min_reached = start_soc_pct
    for weight, slot_load_kwh in zip(_SOLAR_SLOT_WEIGHTS, day.slot_loads_kwh, strict=True):
        net_pct = (day.forecast_kwh * weight - slot_load_kwh) / day.battery_capacity_kwh * 100
        soc_pct = max(0.0, min(100.0, soc_pct + net_pct))
        min_reached = min(min_reached, soc_pct)
    return min_reached


def _find_minimum_charge_target(day: _SimulatedDay, min_soc: int) -> int:
    """
    Binary search for the lowest overnight target SoC that keeps the battery
    above min_soc throughout the simulated day.

    More charge → higher min SoC → monotonically safe to binary search.
    """
    lo, hi = min_soc, 100
    while lo < hi:
        mid = (lo + hi) // 2
        if _simulate_min_soc(mid, day) >= min_soc:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _blend_forecast_p10(
    forecast_kwh: float,
    forecast_kwh_p10: float | None,
    conservatism: float,
) -> tuple[float, str]:
    """Return (blended_forecast_kwh, blend_suffix_for_reason_string)."""
    if forecast_kwh_p10 is None or conservatism <= 0.0:
        return forecast_kwh, ""
    weight = max(0.0, min(1.0, conservatism))
    blended = (1.0 - weight) * forecast_kwh + weight * forecast_kwh_p10
    return blended, f" (P10/P50 blend, conservatism={weight:.2f})"


@dataclass
class ChargeDecision:
    """Result of the overnight charge calculation."""

    target_soc: int
    skip_charge: bool
    reason: str
    forecast_kwh: float
    current_soc: float
    battery_capacity: float
    car_plugged_in: bool
    cost_to_charge: float


@dataclass(frozen=True)
class ChargeInputs:
    """The battery, load and tariff figures tonight's charge target is worked out from."""

    current_soc: float
    battery_capacity_kwh: float
    min_soc: int
    skip_charge_threshold: int
    car_plugged_in: bool
    inverter_max_kw: float
    average_daily_consumption_kwh: float
    cheapest_rate: float
    load_profile: list[float] | None = None
    solar_power_w: float = 0.0


@dataclass(frozen=True)
class SolarForecast:
    """The solar forecasts (p50 and p10) for the day the charge serves and the day after it."""

    forecast_kwh: float | None
    solar_fractions: dict[int, float] | None = None
    forecast_kwh_p10: float | None = None
    forecast_conservatism: float = 0.0
    forecast_kwh_d2: float | None = None
    forecast_correction: float | None = None


@dataclass(frozen=True)
class _ResolvedForecast:
    kwh: float
    source: str


@dataclass(frozen=True)
class _Tonight:
    """Everything the non-winter steps need, with the forecast resolved."""

    inputs: ChargeInputs
    min_soc: int
    forecast_kwh: float
    forecast_source: str
    forecast_kwh_d2: float | None


@dataclass(frozen=True)
class _SkipCheck:
    skips: bool
    blocked_note: str = ""


@dataclass(frozen=True)
class _ChargePlan:
    """The decision before the battery figures are copied in from ChargeInputs."""

    target_soc: int
    skip_charge: bool
    reason: str
    forecast_kwh: float
    cost_to_charge: float


def _cost_to_charge(inputs: ChargeInputs, target_soc: int) -> float:
    kwh_to_charge = max(0.0, inputs.battery_capacity_kwh * (target_soc - inputs.current_soc) / 100)
    return kwh_to_charge * inputs.cheapest_rate


def _build_decision(inputs: ChargeInputs, plan: _ChargePlan) -> ChargeDecision:
    """The only place a ChargeDecision is constructed."""
    return ChargeDecision(
        target_soc=plan.target_soc,
        skip_charge=plan.skip_charge,
        reason=plan.reason,
        forecast_kwh=plan.forecast_kwh,
        current_soc=inputs.current_soc,
        battery_capacity=inputs.battery_capacity_kwh,
        car_plugged_in=inputs.car_plugged_in,
        cost_to_charge=plan.cost_to_charge,
    )


def _winter_plan(inputs: ChargeInputs, month: int) -> _ChargePlan:
    """Solar is negligible in Dec-Feb, so always fill the battery.

    Skips the forecast simulation entirely. That saves a register write and is
    nearly always the correct decision.
    """
    return _ChargePlan(
        target_soc=100,
        skip_charge=inputs.current_soc >= CHARGE_WINTER_SKIP_SOC_PCT,
        reason=f"Winter month ({month}) — charging to 100%.",
        forecast_kwh=0.0,
        cost_to_charge=_cost_to_charge(inputs, 100),
    )


def _seasonal_min_soc(configured_min_soc: int, month: int) -> int:
    """Shoulder months raise the floor: heating load varies and the forecast is less reliable."""
    if month in CHARGE_SHOULDER_MONTHS:
        return max(configured_min_soc, CHARGE_SHOULDER_MIN_SOC)
    return configured_min_soc


def _seasonal_forecast(
    inputs: ChargeInputs, forecast: SolarForecast, month: int
) -> _ResolvedForecast:
    """Estimate tomorrow's yield from latitude when no forecast integration is configured."""
    fractions = forecast.solar_fractions or {}
    seasonal_fraction = fractions.get(month, 0.5)
    estimated_peak_hours = CHARGE_PEAK_SOLAR_HOURS * seasonal_fraction
    return _ResolvedForecast(
        kwh=inputs.inverter_max_kw * estimated_peak_hours,
        source=f"seasonal estimate (month={month}, lat-derived)",
    )


def _integration_forecast(forecast_kwh: float, correction: float | None) -> _ResolvedForecast:
    """Use the integration's forecast, scaled by how accurate it has recently been."""
    source = "forecast integration"
    if correction is not None and correction != 1.0:
        forecast_kwh *= correction
        source += f", x{correction:.2f} recent accuracy"
    return _ResolvedForecast(kwh=forecast_kwh, source=source)


def _missing_p10_note(forecast: SolarForecast) -> str:
    """Say so when conservatism is set but the integration forecast has no P10 to blend with."""
    if forecast.forecast_kwh is None or forecast.forecast_kwh_p10 is not None:
        return ""
    if forecast.forecast_conservatism <= 0.0:
        return ""
    return ", no P10 forecast so conservatism is unused"


def _resolve_forecast(
    inputs: ChargeInputs, forecast: SolarForecast, month: int
) -> _ResolvedForecast:
    if forecast.forecast_kwh is None:
        base = _seasonal_forecast(inputs, forecast, month)
    else:
        base = _integration_forecast(forecast.forecast_kwh, forecast.forecast_correction)
    blended_kwh, blend_suffix = _blend_forecast_p10(
        base.kwh, forecast.forecast_kwh_p10, forecast.forecast_conservatism
    )
    return _ResolvedForecast(
        kwh=blended_kwh, source=base.source + blend_suffix + _missing_p10_note(forecast)
    )


def _is_skip_candidate(tonight: _Tonight) -> bool:
    """High enough battery, no car, and a forecast well above what the battery can absorb."""
    inputs = tonight.inputs
    usable_capacity = inputs.battery_capacity_kwh * (1 - tonight.min_soc / 100)
    expected_solar_fill = min(tonight.forecast_kwh * CHARGE_SOLAR_USABLE_FRACTION, usable_capacity)
    return (
        inputs.current_soc >= inputs.skip_charge_threshold
        and not inputs.car_plugged_in
        and tonight.forecast_kwh > expected_solar_fill * CHARGE_SKIP_HEADROOM
    )


def _try_skip(tonight: _Tonight, dt: datetime) -> _SkipCheck:
    """Skip only if the battery also lasts until solar starts, as the survival sensor judges it."""
    if not _is_skip_candidate(tonight):
        return _SkipCheck(skips=False)
    inputs = tonight.inputs
    survives, _, survival_note = estimate_will_survive_night(
        NightEstimateInputs(
            current_soc=inputs.current_soc,
            battery_capacity_kwh=inputs.battery_capacity_kwh,
            min_soc=float(inputs.min_soc),
            hours_until_solar=hours_until_solar(dt.hour, inputs.solar_power_w),
            average_hourly_consumption_kwh=inputs.average_daily_consumption_kwh / 24,
        )
    )
    if survives:
        return _SkipCheck(skips=True)
    return _SkipCheck(skips=False, blocked_note=f" Not skipping: {survival_note}")


def _skip_plan(tonight: _Tonight) -> _ChargePlan:
    return _ChargePlan(
        target_soc=tonight.min_soc + CHARGE_STRONG_BUFFER,
        skip_charge=True,
        reason=(
            f"Battery at {tonight.inputs.current_soc:.0f}%, good solar forecast "
            f"({tonight.forecast_kwh:.1f}kWh from {tonight.forecast_source}). "
            "Skipping overnight charge."
        ),
        forecast_kwh=tonight.forecast_kwh,
        cost_to_charge=0.0,
    )


def _overmorrow_reduction(tonight: _Tonight) -> int:
    """
    PALM overmorrow correction: if d+2 solar would overflow the battery, reduce
    tonight's target proportionally (percentage points). Zero when EV is connected.
    """
    if tonight.forecast_kwh_d2 is None or tonight.inputs.car_plugged_in:
        return 0
    d2_fill_pct = (tonight.forecast_kwh_d2 / tonight.inputs.battery_capacity_kwh) * 100
    if d2_fill_pct <= 100:
        return 0
    return max(0, int((d2_fill_pct - 100) / 2))


def _simulated_plan(tonight: _Tonight, skip_blocked_note: str) -> _ChargePlan:
    """Forward SoC simulation (PALM algorithm).

    Binary-searches for the minimum overnight charge that keeps SoC >= min_soc
    throughout the simulated day (48 half-hour slots, bell-curve solar profile).
    """
    inputs = tonight.inputs
    day = _SimulatedDay(
        tonight.forecast_kwh,
        inputs.battery_capacity_kwh,
        _slot_loads_kwh(inputs.average_daily_consumption_kwh, inputs.load_profile),
    )
    target_soc = _find_minimum_charge_target(day, tonight.min_soc)
    reason = (
        f"Forward simulation: {tonight.forecast_kwh:.1f}kWh forecast "
        f"({tonight.forecast_source}). Target {target_soc}%.{skip_blocked_note}"
    )
    if _profile_usable(inputs.load_profile):
        reason += " Per-slot load profile used."

    reduction = _overmorrow_reduction(tonight)
    if reduction > 0:
        target_soc = max(tonight.min_soc, target_soc - reduction)
        reason += f" Overmorrow {tonight.forecast_kwh_d2:.1f}kWh → reduced target by {reduction}%."

    if inputs.car_plugged_in:
        target_soc = min(100, target_soc + CHARGE_EV_SOC_BONUS)
        reason += " Car plugged in — added buffer."

    target_soc = min(max(target_soc, tonight.min_soc + CHARGE_MIN_TARGET_HEADROOM_PCT), 100)
    return _ChargePlan(
        target_soc=target_soc,
        skip_charge=False,
        reason=reason,
        forecast_kwh=tonight.forecast_kwh,
        cost_to_charge=_cost_to_charge(inputs, target_soc),
    )


def calculate_overnight_charge_target(
    inputs: ChargeInputs,
    forecast: SolarForecast,
    dt: datetime,
) -> ChargeDecision:
    """
    Calculate the optimal overnight charge target SoC.

    Uses a 48-slot (30-min) forward SoC simulation (PALM algorithm) to find the
    minimum overnight charge that keeps battery SoC above min_soc throughout the day.

    Algorithm parameters (CHARGE_* in const.py):
      CHARGE_PEAK_SOLAR_HOURS      — peak hours at full output for seasonal fallback
      CHARGE_SOLAR_USABLE_FRACTION — fraction of forecast we can realistically use for skip check
      CHARGE_SKIP_HEADROOM         — how far forecast must exceed fill before skipping
      CHARGE_STRONG_BUFFER         — SoC buffer added to skip_charge target
      CHARGE_EV_SOC_BONUS          — extra % added to target when EV is connected

    Skipping also needs the battery to last until solar starts. That check uses the
    same window, inputs and minimum SoC as the night survival sensor (hours_until_solar
    and estimate_will_survive_night), so the plan never skips a charge the survival
    sensor calls Critical. inputs.solar_power_w tells it whether the sun is still up.
    """
    if dt.month in CHARGE_WINTER_MONTHS:
        return _build_decision(inputs, _winter_plan(inputs, dt.month))

    resolved = _resolve_forecast(inputs, forecast, dt.month)
    tonight = _Tonight(
        inputs=inputs,
        min_soc=_seasonal_min_soc(inputs.min_soc, dt.month),
        forecast_kwh=resolved.kwh,
        forecast_source=resolved.source,
        forecast_kwh_d2=forecast.forecast_kwh_d2,
    )
    skip = _try_skip(tonight, dt)
    if skip.skips:
        return _build_decision(inputs, _skip_plan(tonight))
    return _build_decision(inputs, _simulated_plan(tonight, skip.blocked_note))


# ── Immersion divert decision ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SurplusInputs:
    """Power flows that decide how much solar is left over."""

    solar_power_w: float
    house_load_w: float
    battery_power_w: float = 0.0
    immersion_on: bool = False
    immersion_power_w: float = 0.0


def available_surplus_w(inputs: SurplusInputs) -> float:
    """
    Solar power left over once the rest of the house and battery charging are served.

    house_load_w is the GivTCP load sensor. It is the inverter-side load and already
    includes the immersion's draw while it is on, so that draw is added back (capped at
    house_load_w). Without this the surplus collapses as soon as the element starts,
    and the next cycle switches it off again. Only positive battery_power_w (charging)
    is subtracted. The EV charger's draw is not added back.
    """
    own_draw_w = (
        min(max(0.0, inputs.immersion_power_w), max(0.0, inputs.house_load_w))
        if inputs.immersion_on
        else 0.0
    )
    return (
        inputs.solar_power_w
        - (inputs.house_load_w - own_draw_w)
        - max(0.0, inputs.battery_power_w)
    )


Verdict = tuple[bool, str]


@dataclass(frozen=True)
class PowerReadings:
    """Live power figures. None means the sensor is unavailable."""

    solar_power_w: float | None
    house_load_w: float | None
    battery_power_w: float | None
    battery_soc: float
    inverter_max_w: float
    immersion_power_w: float = 0.0


@dataclass(frozen=True)
class WaterState:
    """Hot water temperatures and the limits they are judged against."""

    temp: float | None
    target_temp: float
    min_temp: float
    hysteresis_c: float = 5.0
    temp_unavailable: bool = False


@dataclass(frozen=True)
class DivertPolicy:
    """The configured thresholds and rates for diverting surplus."""

    soc_threshold: int = SURPLUS_DIVERT_SOC_THRESHOLD
    min_surplus_w: float = SURPLUS_DIVERT_MIN_POWER_W
    battery_cycle_cost_per_kwh: float = 0.0
    export_rate: float = 0.0
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL


@dataclass(frozen=True)
class ImmersionRun:
    """Whether the element is on now, and how long its inputs have been unavailable."""

    currently_on: bool = False
    unavailable_for_s: float = 0.0


@dataclass(frozen=True)
class ImmersionInputs:
    power: PowerReadings
    water: WaterState
    policy: DivertPolicy = field(default_factory=DivertPolicy)
    run: ImmersionRun = field(default_factory=ImmersionRun)


@dataclass(frozen=True)
class _Readings:
    """The three power sensors, all available."""

    solar_power_w: float
    house_load_w: float
    battery_power_w: float


@dataclass(frozen=True)
class _Surplus:
    net_w: float
    required_w: float
    at_capacity: bool

    @property
    def sufficient(self) -> bool:
        return self.net_w >= self.required_w or self.at_capacity


def _required_readings(power: PowerReadings) -> _Readings | None:
    if power.solar_power_w is None or power.house_load_w is None or power.battery_power_w is None:
        return None
    return _Readings(power.solar_power_w, power.house_load_w, power.battery_power_w)


def _missing_inputs(inputs: ImmersionInputs) -> list[str]:
    """Names of required decision inputs that are unavailable."""
    power = inputs.power
    missing = [
        name
        for name, value in (
            ("solar_power", power.solar_power_w),
            ("house_load", power.house_load_w),
            ("battery_power", power.battery_power_w),
        )
        if value is None
    ]
    if inputs.water.temp_unavailable:
        missing.append("immersion_temp")
    return missing


def _missing_input_decision(missing: list[str], run: ImmersionRun) -> Verdict:
    """Hold an already-running element for a bounded time, never start on missing data."""
    names = ", ".join(missing)
    if not run.currently_on:
        return False, f"Sensor unavailable ({names}), not starting"
    if run.unavailable_for_s < SENSOR_OUTAGE_HOLD_LIMIT_S:
        return True, f"Sensor unavailable ({names}), holding on"
    return False, (
        f"Sensor unavailable ({names}) for {run.unavailable_for_s:.0f}s, "
        f"hold limit {SENSOR_OUTAGE_HOLD_LIMIT_S}s reached, turning off"
    )


def _water_temperature_decision(water: WaterState) -> Verdict | None:
    """Legionella floor (always heat) and target ceiling (stop), or None when between."""
    if water.temp is None:
        return None
    if water.temp < water.min_temp:
        return True, (
            f"Water at {water.temp:.1f}°C — below minimum safe temperature "
            f"{water.min_temp:.0f}°C, heating regardless of surplus"
        )
    if water.temp >= water.target_temp:
        return False, f"Water already at {water.temp:.1f}°C (target {water.target_temp}°C)"
    return None


def _assess_surplus(inputs: ImmersionInputs, readings: _Readings) -> _Surplus:
    """Once on, the element stays on while the surplus is no worse than -min_surplus_w."""
    power, policy = inputs.power, inputs.policy
    net_w = available_surplus_w(
        SurplusInputs(
            readings.solar_power_w,
            readings.house_load_w,
            readings.battery_power_w,
            inputs.run.currently_on,
            power.immersion_power_w,
        )
    )
    clipping_w = power.inverter_max_w * CLIPPING_THRESHOLD_PERCENT / 100
    is_clipping = readings.solar_power_w >= clipping_w
    return _Surplus(
        net_w=net_w,
        required_w=-policy.min_surplus_w if inputs.run.currently_on else policy.min_surplus_w,
        at_capacity=is_clipping and power.battery_soc >= policy.soc_threshold,
    )


def _cycle_cost_block(policy: DivertPolicy) -> Verdict | None:
    cycle_cost = policy.battery_cycle_cost_per_kwh
    if cycle_cost > 0 and 0 < policy.export_rate < cycle_cost:
        symbol = policy.currency_symbol
        return False, (
            f"Export rate {policy.export_rate:.4f} {symbol}/kWh is below battery cycle cost "
            f"{cycle_cost:.4f} {symbol}/kWh — not worth cycling"
        )
    return None


def _restart_block(water: WaterState, run: ImmersionRun) -> Verdict | None:
    """Surplus is available, but only restart once the water has cooled enough."""
    if water.temp is not None and not run.currently_on:
        turn_on_below = water.target_temp - water.hysteresis_c
        if water.temp >= turn_on_below:
            return False, (
                f"Water at {water.temp:.1f}°C — will restart below {turn_on_below:.0f}°C"
            )
    return None


def _surplus_decision(inputs: ImmersionInputs, readings: _Readings) -> Verdict:
    power = inputs.power
    if power.battery_soc < inputs.policy.soc_threshold:
        return False, (
            f"Battery SoC {power.battery_soc:.0f}% below threshold {inputs.policy.soc_threshold}%"
        )
    surplus = _assess_surplus(inputs, readings)
    if not surplus.sufficient:
        return False, (
            f"Insufficient surplus ({surplus.net_w:.0f}W, need {surplus.required_w:.0f}W)"
        )
    blocked = _cycle_cost_block(inputs.policy) or _restart_block(inputs.water, inputs.run)
    if blocked is not None:
        return blocked
    if surplus.at_capacity:
        return True, (
            f"Inverter at capacity ({readings.solar_power_w:.0f}W), "
            f"battery {power.battery_soc:.0f}% — diverting to immersion"
        )
    return True, (
        f"Solar surplus {surplus.net_w:.0f}W available, battery at {power.battery_soc:.0f}%"
    )


def should_divert_to_immersion(inputs: ImmersionInputs) -> Verdict:
    """
    Decide whether to turn on the immersion heater.

    Returns (should_divert, reason).

    Algorithm:
      1. Always heat if below legionella minimum temperature (ignores hysteresis)
      2. Turn off when target temperature is reached
      3. If a required input is missing (None solar, house load or battery power,
         or water.temp_unavailable): never start on missing data. If already on,
         hold on while run.unavailable_for_s is below SENSOR_OUTAGE_HOLD_LIMIT_S, then
         turn off. The caller measures unavailable_for_s so this function stays pure.
      4. Hysteresis: if currently off, only restart once water cools to
         (target - hysteresis_c); if currently on, keep running until target
      5. Never heat if battery SoC is below soc_threshold
      6. Start when available surplus >= min_surplus_w. Once on, stay on while
         the available surplus (with the element's own draw added back) is
         >= -min_surplus_w.
      7. Heat if inverter is clipping (at capacity) and battery is charged

    The hysteresis band prevents rapid on/off cycling near the target temperature.
    With defaults of target=55°C and hysteresis=5°C: turns off at 55°C and will
    not restart until water drops below 50°C.
    """
    temperature_decision = _water_temperature_decision(inputs.water)
    if temperature_decision is not None:
        return temperature_decision
    readings = _required_readings(inputs.power)
    missing = _missing_inputs(inputs)
    if missing or readings is None:
        return _missing_input_decision(missing, inputs.run)
    return _surplus_decision(inputs, readings)


# ── Appliance timing suggestion ───────────────────────────────────────────────


@dataclass(frozen=True)
class SiteReadings:
    """Live power and battery figures at the site."""

    solar_power_w: float
    house_load_w: float
    battery_soc: float
    battery_power_w: float


@dataclass(frozen=True)
class ApplianceRequest:
    name: str
    power_w: float


@dataclass(frozen=True)
class RateContext:
    """The current import rate, its period name, and the export rate to compare it with."""

    period_name: str
    rate: float
    export_rate: float
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL


def _too_expensive_reason(appliance: ApplianceRequest, rates: RateContext) -> str:
    cost = (appliance.power_w / 1000) * rates.rate
    return (
        f"Not recommended: {appliance.name} would cost "
        f"~{rates.currency_symbol}{cost:.3f} "
        f"at current {rates.period_name} rate. Wait for solar surplus or cheap rate."
    )


def suggest_appliance_run(
    site: SiteReadings,
    appliance: ApplianceRequest,
    rates: RateContext,
) -> Verdict:
    """
    Suggest whether now is a good time to run a high-load appliance.

    Returns (recommended, reason).

    Recommends if:
      - There is enough solar surplus to power the appliance (free to run)
      - Battery is at APPLIANCE_MIN_BATTERY_SOC and rate is near export rate
    Does not recommend if the current rate is more than APPLIANCE_RATE_THRESHOLD
    times the export rate.
    """
    net_surplus_w = available_surplus_w(
        SurplusInputs(site.solar_power_w, site.house_load_w, site.battery_power_w)
    )
    symbol = rates.currency_symbol
    rate_ceiling = rates.export_rate * APPLIANCE_RATE_THRESHOLD

    if net_surplus_w >= appliance.power_w:
        saving = (appliance.power_w / 1000) * rates.rate
        return True, (
            f"Good time to run {appliance.name}: {net_surplus_w:.0f}W surplus available. "
            f"Running now saves ~{symbol}{saving:.3f} vs grid rate."
        )

    if site.battery_soc >= APPLIANCE_MIN_BATTERY_SOC and rates.rate <= rate_ceiling:
        return True, (
            f"Acceptable time to run {appliance.name}: battery at {site.battery_soc:.0f}%, "
            f"currently on {rates.period_name} rate ({symbol}{rates.rate:.4f}/kWh)."
        )

    if rates.rate > rate_ceiling:
        return False, _too_expensive_reason(appliance, rates)

    return False, f"No strong reason to run {appliance.name} right now."


# ── EV charger decisions ──────────────────────────────────────────────────────


def decide_ev_charger_action(
    charger: EVCharger,
    battery_soc: float,
    solar_surplus_w: float,
) -> tuple[str | None, str]:
    """
    Decide what mode the EV charger should be in.

    Returns (target_mode_or_None, reason).

    Rules (in priority order):
      1. No plugged-in vehicle → no change
      2. Surplus below EV_CHARGER_MIN_POWER_W (the charger cannot start) → no change
      3. Zappi not already in Eco+ → switch to Eco+
      4. Otherwise → no change
    """
    if not charger.is_plugged_in:
        return None, "EV not connected"

    # Minimum power guard: OCPP chargers will not start below 6A (1,380W at 230V).
    # Sending an Eco+ command when surplus is below this threshold wastes a register
    # write and causes the charger to oscillate at the threshold boundary.
    if solar_surplus_w < EV_CHARGER_MIN_POWER_W:
        return None, (
            f"Surplus {solar_surplus_w:.0f}W below charger minimum {EV_CHARGER_MIN_POWER_W}W — "
            f"not starting"
        )

    if charger.brand == EVChargerBrand.ZAPPI:
        current = (charger.charge_mode or "").lower()
        if current not in ("eco+",):
            return ZAPPI_ECO_PLUS_MODE, (
                f"Solar surplus {solar_surplus_w:.0f}W available, battery at "
                f"{battery_soc:.0f}% — switching to Eco+ to absorb surplus"
            )
        return None, f"Already in Eco+ with {solar_surplus_w:.0f}W surplus"

    return None, (
        f"Battery SoC {battery_soc:.0f}% OK, surplus {solar_surplus_w:.0f}W — no action needed"
    )



# ── Pre-cheap-rate export opportunity ─────────────────────────────────────────


@dataclass(frozen=True)
class PreBoostInputs:
    """Battery state, tonight's target and the two rates that decide an early export."""

    current_soc: float
    battery_capacity_kwh: float
    target_soc: int
    avg_daily_kwh: float
    ceg_rate: float
    cheapest_rate: float
    min_spare_kwh: float = 1.0


def calculate_pre_boost_export_opportunity(inputs: PreBoostInputs) -> tuple[float, float, bool]:
    """
    Calculate whether it's worth exporting before the cheap rate window.

    Returns (spare_kwh, net_gain, recommended).

    spare_kwh:   kWh available to export before overnight charge (0 if none)
    net_gain:    estimated gain (configured currency) from exporting now and recharging
                 at the boost rate
    recommended: True when net_gain > 0 and spare_kwh >= inputs.min_spare_kwh

    Formula:
      spare_kwh = current_soc_kwh - overnight_deficit_kwh - evening_load_est_kwh
      net_gain  = spare_kwh × (ceg_rate - cheapest_rate)

    The evening load estimate uses CHARGE_MORNING_LOAD_FRACTION (25% of daily avg)
    as a conservative proxy for evening consumption before the cheap window opens.
    """
    capacity_kwh = inputs.battery_capacity_kwh
    current_soc_kwh = capacity_kwh * (inputs.current_soc / 100)
    target_soc_kwh = capacity_kwh * (inputs.target_soc / 100)
    overnight_deficit_kwh = max(0.0, target_soc_kwh - current_soc_kwh)
    evening_load_est_kwh = inputs.avg_daily_kwh * CHARGE_MORNING_LOAD_FRACTION
    spare_kwh = max(0.0, current_soc_kwh - overnight_deficit_kwh - evening_load_est_kwh)
    net_gain = spare_kwh * (inputs.ceg_rate - inputs.cheapest_rate)
    recommended = net_gain > 0.0 and spare_kwh >= inputs.min_spare_kwh
    return round(spare_kwh, 3), round(net_gain, 4), recommended
