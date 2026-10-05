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
from dataclasses import dataclass
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
from .battery import estimate_will_survive_night, hours_until_solar

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


def _simulate_min_soc(  # noqa: PLR0913
    start_soc_pct: float,
    forecast_kwh: float,
    avg_daily_kwh: float,
    battery_capacity_kwh: float,
    load_profile: list[float] | None = None,
) -> float:
    """Simulate one day starting from start_soc_pct. Return the minimum SoC reached."""
    slot_loads = _slot_loads_kwh(avg_daily_kwh, load_profile)
    soc_pct = start_soc_pct
    min_reached = start_soc_pct
    for weight, slot_load_kwh in zip(_SOLAR_SLOT_WEIGHTS, slot_loads, strict=True):
        net_pct = (forecast_kwh * weight - slot_load_kwh) / battery_capacity_kwh * 100
        soc_pct = max(0.0, min(100.0, soc_pct + net_pct))
        min_reached = min(min_reached, soc_pct)
    return min_reached


def _find_minimum_charge_target(  # noqa: PLR0913
    forecast_kwh: float,
    avg_daily_kwh: float,
    battery_capacity_kwh: float,
    min_soc: int,
    load_profile: list[float] | None = None,
) -> int:
    """
    Binary search for the lowest overnight target SoC that keeps the battery
    above min_soc throughout the simulated day.

    More charge → higher min SoC → monotonically safe to binary search.
    """
    lo, hi = min_soc, 100
    while lo < hi:
        mid = (lo + hi) // 2
        if (
            _simulate_min_soc(mid, forecast_kwh, avg_daily_kwh, battery_capacity_kwh, load_profile)
            >= min_soc
        ):
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


def _apply_overmorrow_correction(  # noqa: PLR0913
    target_soc: int,
    reason: str,
    forecast_kwh_d2: float | None,
    battery_capacity_kwh: float,
    min_soc: int,
    car_plugged_in: bool,  # noqa: FBT001
) -> tuple[int, str]:
    """
    PALM overmorrow correction: if d+2 solar would overflow the battery, reduce
    tonight's target proportionally. Skipped when EV is connected.
    """
    if forecast_kwh_d2 is None or car_plugged_in:
        return target_soc, reason
    d2_fill_pct = (forecast_kwh_d2 / battery_capacity_kwh) * 100
    if d2_fill_pct <= 100:
        return target_soc, reason
    overflow_pct = d2_fill_pct - 100
    reduction = int(overflow_pct / 2)
    if reduction <= 0:
        return target_soc, reason
    target_soc = max(min_soc, target_soc - reduction)
    reason += f" Overmorrow {forecast_kwh_d2:.1f}kWh → reduced target by {reduction}%."
    return target_soc, reason


def calculate_overnight_charge_target(  # noqa: C901, PLR0913, PLR0915
    current_soc: float,
    battery_capacity_kwh: float,
    forecast_kwh: float | None,
    inverter_max_kw: float,
    car_plugged_in: bool,  # noqa: FBT001
    min_soc: int,
    skip_charge_threshold: int,
    average_daily_consumption_kwh: float,
    cheapest_rate: float,
    solar_fractions: dict[int, float] | None = None,
    forecast_kwh_p10: float | None = None,
    forecast_conservatism: float = 0.0,
    forecast_kwh_d2: float | None = None,
    load_profile: list[float] | None = None,
    forecast_correction: float | None = None,
    solar_generating: bool = True,  # noqa: FBT001, FBT002
    *,
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
    sensor calls Critical. solar_generating tells it whether the sun is still up.
    """
    month = dt.month

    # Winter bypass: solar is negligible in Dec–Feb; always fill the battery.
    # Skips the forecast simulation entirely — saves a register write and is
    # nearly always the correct decision.
    if month in CHARGE_WINTER_MONTHS:
        kwh_to_charge = max(0.0, battery_capacity_kwh * (100 - current_soc) / 100)
        return ChargeDecision(
            target_soc=100,
            skip_charge=current_soc >= CHARGE_WINTER_SKIP_SOC_PCT,
            reason=f"Winter month ({month}) — charging to 100%.",
            forecast_kwh=0.0,
            current_soc=current_soc,
            battery_capacity=battery_capacity_kwh,
            car_plugged_in=car_plugged_in,
            cost_to_charge=kwh_to_charge * cheapest_rate,
        )

    configured_min_soc = min_soc

    # Shoulder months: raise the min_soc floor — heating load is more variable
    # and the forecast is less reliable than in peak summer.
    if month in CHARGE_SHOULDER_MONTHS:
        min_soc = max(min_soc, CHARGE_SHOULDER_MIN_SOC)

    if forecast_kwh is None:
        fractions = solar_fractions or {}
        seasonal_fraction = fractions.get(month, 0.5)
        estimated_peak_hours = CHARGE_PEAK_SOLAR_HOURS * seasonal_fraction
        forecast_kwh = inverter_max_kw * estimated_peak_hours
        forecast_source = f"seasonal estimate (month={month}, lat-derived)"
    else:
        forecast_source = "forecast integration"
        if forecast_correction is not None and forecast_correction != 1.0:
            forecast_kwh *= forecast_correction
            forecast_source += f", x{forecast_correction:.2f} recent accuracy"

    forecast_kwh, blend_suffix = _blend_forecast_p10(
        forecast_kwh, forecast_kwh_p10, forecast_conservatism
    )
    forecast_source += blend_suffix

    usable_capacity = battery_capacity_kwh * (1 - min_soc / 100)
    expected_solar_fill = min(forecast_kwh * CHARGE_SOLAR_USABLE_FRACTION, usable_capacity)

    skip_blocked_note = ""
    if (
        current_soc >= skip_charge_threshold
        and not car_plugged_in
        and forecast_kwh > expected_solar_fill * CHARGE_SKIP_HEADROOM
    ):
        survives, _, survival_note = estimate_will_survive_night(
            current_soc=current_soc,
            battery_capacity_kwh=battery_capacity_kwh,
            min_soc=float(configured_min_soc),
            hours_until_solar=hours_until_solar(dt.hour, solar_generating),
            average_hourly_consumption_kwh=average_daily_consumption_kwh / 24,
        )
        if survives:
            return ChargeDecision(
                target_soc=min_soc + CHARGE_STRONG_BUFFER,
                skip_charge=True,
                reason=(
                    f"Battery at {current_soc:.0f}%, good solar forecast "
                    f"({forecast_kwh:.1f}kWh from {forecast_source}). Skipping overnight charge."
                ),
                forecast_kwh=forecast_kwh,
                current_soc=current_soc,
                battery_capacity=battery_capacity_kwh,
                car_plugged_in=car_plugged_in,
                cost_to_charge=0.0,
            )
        skip_blocked_note = f" Not skipping: {survival_note}"

    # Forward SoC simulation (PALM algorithm) — replaces the three-tier lookup.
    # Binary-search for the minimum overnight charge that keeps SoC >= min_soc
    # throughout the simulated day (48 half-hour slots, bell-curve solar profile).
    target_soc = _find_minimum_charge_target(
        forecast_kwh,
        average_daily_consumption_kwh,
        battery_capacity_kwh,
        min_soc,
        load_profile,
    )
    reason = (
        f"Forward simulation: {forecast_kwh:.1f}kWh forecast ({forecast_source}). "
        f"Target {target_soc}%.{skip_blocked_note}"
    )
    if _profile_usable(load_profile):
        reason += " Per-slot load profile used."

    target_soc, reason = _apply_overmorrow_correction(
        target_soc, reason, forecast_kwh_d2, battery_capacity_kwh, min_soc, car_plugged_in
    )

    if car_plugged_in:
        target_soc = min(100, target_soc + CHARGE_EV_SOC_BONUS)
        reason += " Car plugged in — added buffer."

    target_soc = max(target_soc, min_soc + CHARGE_MIN_TARGET_HEADROOM_PCT)
    target_soc = min(target_soc, 100)

    kwh_to_charge = max(0, battery_capacity_kwh * (target_soc - current_soc) / 100)
    cost_to_charge = kwh_to_charge * cheapest_rate

    return ChargeDecision(
        target_soc=target_soc,
        skip_charge=False,
        reason=reason,
        forecast_kwh=forecast_kwh,
        current_soc=current_soc,
        battery_capacity=battery_capacity_kwh,
        car_plugged_in=car_plugged_in,
        cost_to_charge=cost_to_charge,
    )


# ── Immersion divert decision ─────────────────────────────────────────────────


def available_surplus_w(  # noqa: PLR0913
    solar_power_w: float,
    house_load_w: float,
    battery_power_w: float = 0.0,
    immersion_on: bool = False,  # noqa: FBT001, FBT002
    immersion_power_w: float = 0.0,
) -> float:
    """
    Solar power left over once the rest of the house and battery charging are served.

    house_load_w is the GivTCP load sensor. It is the inverter-side load and already
    includes the immersion's draw while it is on, so that draw is added back (capped at
    house_load_w). Without this the surplus collapses as soon as the element starts,
    and the next cycle switches it off again. Only positive battery_power_w (charging)
    is subtracted. The EV charger's draw is not added back.
    """
    own_draw_w = min(max(0.0, immersion_power_w), max(0.0, house_load_w)) if immersion_on else 0.0
    return solar_power_w - (house_load_w - own_draw_w) - max(0.0, battery_power_w)


def _missing_inputs(
    solar_power_w: float | None,
    house_load_w: float | None,
    battery_power_w: float | None,
    immersion_temp_unavailable: bool,  # noqa: FBT001
) -> list[str]:
    """Names of required decision inputs that are unavailable."""
    missing = [
        name
        for name, value in (
            ("solar_power", solar_power_w),
            ("house_load", house_load_w),
            ("battery_power", battery_power_w),
        )
        if value is None
    ]
    if immersion_temp_unavailable:
        missing.append("immersion_temp")
    return missing


def _missing_input_decision(
    missing: list[str], currently_on: bool, unavailable_for_s: float  # noqa: FBT001
) -> tuple[bool, str]:
    """Hold an already-running element for a bounded time, never start on missing data."""
    names = ", ".join(missing)
    if not currently_on:
        return False, f"Sensor unavailable ({names}), not starting"
    if unavailable_for_s < SENSOR_OUTAGE_HOLD_LIMIT_S:
        return True, f"Sensor unavailable ({names}), holding on"
    return False, (
        f"Sensor unavailable ({names}) for {unavailable_for_s:.0f}s, "
        f"hold limit {SENSOR_OUTAGE_HOLD_LIMIT_S}s reached, turning off"
    )


def should_divert_to_immersion(  # noqa: C901, PLR0913
    solar_power_w: float | None,
    house_load_w: float | None,
    battery_soc: float,
    battery_power_w: float | None,
    inverter_max_w: float,
    immersion_temp: float | None,
    immersion_target_temp: float,
    immersion_min_temp: float,
    immersion_hysteresis_c: float = 5.0,
    currently_on: bool = False,  # noqa: FBT001, FBT002
    soc_threshold: int = SURPLUS_DIVERT_SOC_THRESHOLD,
    min_surplus_w: float = SURPLUS_DIVERT_MIN_POWER_W,
    battery_cycle_cost_per_kwh: float = 0.0,
    export_rate: float = 0.0,
    immersion_power_w: float = 0.0,
    immersion_temp_unavailable: bool = False,  # noqa: FBT001, FBT002
    unavailable_for_s: float = 0.0,
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL,
) -> tuple[bool, str]:
    """
    Decide whether to turn on the immersion heater.

    Returns (should_divert, reason).

    Algorithm:
      1. Always heat if below legionella minimum temperature (ignores hysteresis)
      2. Turn off when target temperature is reached
      3. If a required input is missing (None solar, house load or battery power,
         or immersion_temp_unavailable): never start on missing data. If already on,
         hold on while unavailable_for_s is below SENSOR_OUTAGE_HOLD_LIMIT_S, then
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
    if immersion_temp is not None and immersion_temp < immersion_min_temp:
        return True, (
            f"Water at {immersion_temp:.1f}°C — below minimum safe temperature "
            f"{immersion_min_temp:.0f}°C, heating regardless of surplus"
        )

    if immersion_temp is not None and immersion_temp >= immersion_target_temp:
        return False, f"Water already at {immersion_temp:.1f}°C (target {immersion_target_temp}°C)"

    missing = _missing_inputs(
        solar_power_w, house_load_w, battery_power_w, immersion_temp_unavailable
    )
    if missing or solar_power_w is None or house_load_w is None or battery_power_w is None:
        return _missing_input_decision(missing, currently_on, unavailable_for_s)

    if battery_soc < soc_threshold:
        return False, f"Battery SoC {battery_soc:.0f}% below threshold {soc_threshold}%"

    net_surplus_w = available_surplus_w(
        solar_power_w, house_load_w, battery_power_w, currently_on, immersion_power_w
    )
    is_clipping = solar_power_w >= (inverter_max_w * CLIPPING_THRESHOLD_PERCENT / 100)
    required_w = -min_surplus_w if currently_on else min_surplus_w
    has_surplus = net_surplus_w >= required_w or (is_clipping and battery_soc >= soc_threshold)

    if not has_surplus:
        return False, f"Insufficient surplus ({net_surplus_w:.0f}W, need {required_w:.0f}W)"

    if battery_cycle_cost_per_kwh > 0 and 0 < export_rate < battery_cycle_cost_per_kwh:
        return False, (
            f"Export rate {export_rate:.4f} {currency_symbol}/kWh is below battery cycle cost "
            f"{battery_cycle_cost_per_kwh:.4f} {currency_symbol}/kWh — not worth cycling"
        )

    # Surplus is available — but only restart if water has cooled enough
    if immersion_temp is not None and not currently_on:
        turn_on_below = immersion_target_temp - immersion_hysteresis_c
        if immersion_temp >= turn_on_below:
            return False, (
                f"Water at {immersion_temp:.1f}°C — will restart below {turn_on_below:.0f}°C"
            )

    if is_clipping and battery_soc >= soc_threshold:
        return True, (
            f"Inverter at capacity ({solar_power_w:.0f}W), "
            f"battery {battery_soc:.0f}% — diverting to immersion"
        )

    return True, f"Solar surplus {net_surplus_w:.0f}W available, battery at {battery_soc:.0f}%"


# ── Appliance timing suggestion ───────────────────────────────────────────────


def suggest_appliance_run(  # noqa: PLR0913
    solar_power_w: float,
    house_load_w: float,
    battery_soc: float,
    battery_power_w: float,
    appliance_power_w: float,
    appliance_name: str,
    rate_period_name: str,
    rate: float,
    export_rate: float,
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL,
) -> tuple[bool, str]:
    """
    Suggest whether now is a good time to run a high-load appliance.

    Returns (recommended, reason).

    Recommends if:
      - There is enough solar surplus to power the appliance (free to run)
      - Battery is at APPLIANCE_MIN_BATTERY_SOC and rate is near export rate
    Does not recommend if the current rate is more than APPLIANCE_RATE_THRESHOLD
    times the export rate.
    """
    net_surplus_w = available_surplus_w(solar_power_w, house_load_w, battery_power_w)

    if net_surplus_w >= appliance_power_w:
        saving = (appliance_power_w / 1000) * rate
        return True, (
            f"Good time to run {appliance_name}: {net_surplus_w:.0f}W surplus available. "
            f"Running now saves ~{currency_symbol}{saving:.3f} vs grid rate."
        )

    if battery_soc >= APPLIANCE_MIN_BATTERY_SOC and rate <= export_rate * APPLIANCE_RATE_THRESHOLD:
        return True, (
            f"Acceptable time to run {appliance_name}: battery at {battery_soc:.0f}%, "
            f"currently on {rate_period_name} rate ({currency_symbol}{rate:.4f}/kWh)."
        )

    if rate > export_rate * APPLIANCE_RATE_THRESHOLD:
        return False, (
            f"Not recommended: {appliance_name} would cost "
            f"~{currency_symbol}{(appliance_power_w / 1000) * rate:.3f} "
            f"at current {rate_period_name} rate. Wait for solar surplus or cheap rate."
        )

    return False, f"No strong reason to run {appliance_name} right now."


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


def calculate_pre_boost_export_opportunity(  # noqa: PLR0913
    current_soc: float,
    battery_capacity_kwh: float,
    target_soc: int,
    avg_daily_kwh: float,
    ceg_rate: float,
    cheapest_rate: float,
    min_spare_kwh: float = 1.0,
) -> tuple[float, float, bool]:
    """
    Calculate whether it's worth exporting before the cheap rate window.

    Returns (spare_kwh, net_gain, recommended).

    spare_kwh:   kWh available to export before overnight charge (0 if none)
    net_gain:    estimated gain (configured currency) from exporting now and recharging
                 at the boost rate
    recommended: True when net_gain > 0 and spare_kwh >= min_spare_kwh

    Formula:
      spare_kwh = current_soc_kwh - overnight_deficit_kwh - evening_load_est_kwh
      net_gain  = spare_kwh × (ceg_rate - cheapest_rate)

    The evening load estimate uses CHARGE_MORNING_LOAD_FRACTION (25% of daily avg)
    as a conservative proxy for evening consumption before the cheap window opens.
    """
    current_soc_kwh = battery_capacity_kwh * (current_soc / 100)
    target_soc_kwh = battery_capacity_kwh * (target_soc / 100)
    overnight_deficit_kwh = max(0.0, target_soc_kwh - current_soc_kwh)
    evening_load_est_kwh = avg_daily_kwh * CHARGE_MORNING_LOAD_FRACTION
    spare_kwh = max(0.0, current_soc_kwh - overnight_deficit_kwh - evening_load_est_kwh)
    net_gain_per_kwh = ceg_rate - cheapest_rate
    net_gain = spare_kwh * net_gain_per_kwh
    recommended = net_gain > 0.0 and spare_kwh >= min_spare_kwh
    return round(spare_kwh, 3), round(net_gain, 4), recommended
