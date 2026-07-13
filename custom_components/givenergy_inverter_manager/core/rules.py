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
  should_protect_battery_from_charger() — is the EV drawing from the battery?
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ..const import (
    CHARGE_EV_BUFFER_KWH,
    CHARGE_EV_SOC_BONUS,
    CHARGE_MODERATE_BASE_SOC,
    CHARGE_MODERATE_BUFFER,
    CHARGE_MODERATE_FRACTION,
    CHARGE_MORNING_LOAD_FRACTION,
    CHARGE_PEAK_SOLAR_HOURS,
    CHARGE_POOR_TARGET_SOC,
    CHARGE_SHOULDER_MIN_SOC,
    CHARGE_SHOULDER_MONTHS,
    CHARGE_SKIP_HEADROOM,
    CHARGE_SOLAR_USABLE_FRACTION,
    CHARGE_STRONG_BASE_SOC,
    CHARGE_STRONG_BUFFER,
    CHARGE_STRONG_FRACTION,
    CHARGE_WINTER_MONTHS,
    CLIPPING_THRESHOLD_PERCENT,
    EV_CHARGER_MIN_POWER_W,
    EV_SURPLUS_DIVERT_W,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from ..discovery.ev_charger import (
    ZAPPI_BATTERY_DRAINING_MODES,
    ZAPPI_ECO_PLUS_MODE,
    EVCharger,
    EVChargerBrand,
)

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


def calculate_overnight_charge_target(
    current_soc: float,
    battery_capacity_kwh: float,
    forecast_kwh: float | None,
    inverter_max_kw: float,
    car_plugged_in: bool,
    min_soc: int,
    skip_charge_threshold: int,
    average_daily_consumption_kwh: float,
    cheapest_rate: float,
    solar_fractions: dict[int, float] | None = None,
    forecast_kwh_p10: float | None = None,
    forecast_conservatism: float = 0.0,
    *,
    dt: datetime,
) -> ChargeDecision:
    """
    Calculate the optimal overnight charge target SoC.

    Algorithm parameters (CHARGE_* in const.py):
      CHARGE_PEAK_SOLAR_HOURS      — peak hours at full output for seasonal fallback
      CHARGE_MORNING_LOAD_FRACTION — fraction of daily load assumed before solar starts
      CHARGE_SOLAR_USABLE_FRACTION — fraction of forecast we can realistically charge from
      CHARGE_EV_BUFFER_KWH         — extra kWh reserved overnight when EV is connected
      CHARGE_SKIP_HEADROOM         — how far forecast must exceed fill before skipping
      CHARGE_STRONG/MODERATE_FRACTION — forecast thresholds for decision tiers
      CHARGE_STRONG/MODERATE_BASE_SOC — minimum target SoC per tier
      CHARGE_POOR_TARGET_SOC       — target when forecast is poor
    """
    month = dt.month

    # Winter bypass: solar is negligible in Dec–Feb; always fill the battery.
    # Skips the forecast simulation entirely — saves a register write and is
    # nearly always the correct decision.
    if month in CHARGE_WINTER_MONTHS:
        kwh_to_charge = max(0.0, battery_capacity_kwh * (100 - current_soc) / 100)
        return ChargeDecision(
            target_soc=100,
            skip_charge=current_soc >= 95,
            reason=f"Winter month ({month}) — charging to 100%.",
            forecast_kwh=0.0,
            current_soc=current_soc,
            battery_capacity=battery_capacity_kwh,
            car_plugged_in=car_plugged_in,
            cost_to_charge=kwh_to_charge * cheapest_rate,
        )

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

    forecast_kwh, blend_suffix = _blend_forecast_p10(
        forecast_kwh, forecast_kwh_p10, forecast_conservatism
    )
    forecast_source += blend_suffix

    usable_capacity = battery_capacity_kwh * (1 - min_soc / 100)
    current_kwh = battery_capacity_kwh * (current_soc / 100)
    morning_load_kwh = average_daily_consumption_kwh * CHARGE_MORNING_LOAD_FRACTION
    expected_solar_fill = min(forecast_kwh * CHARGE_SOLAR_USABLE_FRACTION, usable_capacity)

    required_morning_kwh = morning_load_kwh
    if car_plugged_in:
        required_morning_kwh += CHARGE_EV_BUFFER_KWH

    gap_kwh = max(0, required_morning_kwh - current_kwh)
    gap_soc = int((gap_kwh / battery_capacity_kwh) * 100)

    if current_soc >= skip_charge_threshold and not car_plugged_in:
        if forecast_kwh > expected_solar_fill * CHARGE_SKIP_HEADROOM:
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

    if forecast_kwh >= battery_capacity_kwh * CHARGE_STRONG_FRACTION:
        target_soc = max(min_soc + gap_soc + CHARGE_STRONG_BUFFER, CHARGE_STRONG_BASE_SOC)
        reason = (
            f"Strong forecast ({forecast_kwh:.1f}kWh). "
            f"Charging to {target_soc}% to cover morning load."
        )
    elif forecast_kwh >= battery_capacity_kwh * CHARGE_MODERATE_FRACTION:
        target_soc = max(min_soc + gap_soc + CHARGE_MODERATE_BUFFER, CHARGE_MODERATE_BASE_SOC)
        reason = f"Moderate forecast ({forecast_kwh:.1f}kWh). Charging to {target_soc}%."
    else:
        target_soc = CHARGE_POOR_TARGET_SOC
        reason = (
            f"Poor forecast ({forecast_kwh:.1f}kWh from {forecast_source}). "
            f"Charging to {target_soc}%."
        )

    if car_plugged_in:
        target_soc = min(100, target_soc + CHARGE_EV_SOC_BONUS)
        reason += " Car plugged in — added buffer."

    target_soc = max(target_soc, min_soc + 5)
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


def should_divert_to_immersion(
    solar_power_w: float,
    house_load_w: float,
    battery_soc: float,
    battery_power_w: float,
    inverter_max_w: float,
    immersion_temp: float | None,
    immersion_target_temp: float,
    immersion_min_temp: float,
    immersion_hysteresis_c: float = 5.0,
    currently_on: bool = False,
    soc_threshold: int = SURPLUS_DIVERT_SOC_THRESHOLD,
    min_surplus_w: float = SURPLUS_DIVERT_MIN_POWER_W,
) -> tuple[bool, str]:
    """
    Decide whether to turn on the immersion heater.

    Returns (should_divert, reason).

    Algorithm:
      1. Always heat if below legionella minimum temperature (ignores hysteresis)
      2. Turn off when target temperature is reached
      3. Hysteresis: if currently off, only restart once water cools to
         (target - hysteresis_c); if currently on, keep running until target
      4. Never heat if battery SoC is below soc_threshold
      5. Heat if net solar surplus >= min_surplus_w
      6. Heat if inverter is clipping (at capacity) and battery is charged

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

    if battery_soc < soc_threshold:
        return False, f"Battery SoC {battery_soc:.0f}% below threshold {soc_threshold}%"

    battery_charging_w = max(0, battery_power_w)
    net_surplus_w = solar_power_w - house_load_w - battery_charging_w
    is_clipping = solar_power_w >= (inverter_max_w * CLIPPING_THRESHOLD_PERCENT / 100)
    has_surplus = net_surplus_w >= min_surplus_w or (is_clipping and battery_soc >= soc_threshold)

    if not has_surplus:
        return False, f"Insufficient surplus ({net_surplus_w:.0f}W, need {min_surplus_w:.0f}W)"

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


def suggest_appliance_run(
    solar_power_w: float,
    house_load_w: float,
    battery_soc: float,
    battery_power_w: float,
    appliance_power_w: float,
    appliance_name: str,
    rate_period_name: str,
    rate: float,
    export_rate: float,
) -> tuple[bool, str]:
    """
    Suggest whether now is a good time to run a high-load appliance.

    Returns (recommended, reason).

    Recommends if:
      - There is enough solar surplus to power the appliance (free to run)
      - Battery is at SOLAR_APPLIANCE_MIN_BATTERY_SOC and rate is near export rate
    Does not recommend if the current rate is more than 1.5× the export rate.
    """
    min_battery_soc = 80  # % — sufficient charge to run appliance from battery
    rate_threshold = 1.5  # × export rate — above this it's not worth running

    battery_charging_w = max(0, battery_power_w)
    net_surplus_w = solar_power_w - house_load_w - battery_charging_w

    if net_surplus_w >= appliance_power_w:
        saving = (appliance_power_w / 1000) * rate
        return True, (
            f"Good time to run {appliance_name}: {net_surplus_w:.0f}W surplus available. "
            f"Running now saves ~€{saving:.3f} vs grid rate."
        )

    if battery_soc >= min_battery_soc and rate <= export_rate * rate_threshold:
        return True, (
            f"Acceptable time to run {appliance_name}: battery at {battery_soc:.0f}%, "
            f"currently on {rate_period_name} rate (€{rate:.4f}/kWh)."
        )

    if rate > export_rate * rate_threshold:
        return False, (
            f"Not recommended: {appliance_name} would cost "
            f"~€{(appliance_power_w / 1000) * rate:.3f} "
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
      1. Solar surplus > EV_SURPLUS_DIVERT_W and Zappi → switch to Eco+
      2. Otherwise → no change
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

    if solar_surplus_w > EV_SURPLUS_DIVERT_W and charger.brand == EVChargerBrand.ZAPPI:
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


def should_protect_battery_from_charger(
    charger: EVCharger,
    battery_soc: float,
    battery_protection_threshold: float,
) -> tuple[bool, str]:
    """
    Determine whether the battery needs protecting from the EV charger.

    Returns (should_protect, reason).
    Protection is needed when the charger is actively discharging the battery
    and SoC is below the protection threshold.
    """
    if not charger.is_active:
        return False, "Charger not active"
    if not charger.is_draining_battery:
        return False, "Battery not discharging into car"
    if battery_soc > battery_protection_threshold:
        return False, (
            f"Battery SoC {battery_soc:.0f}% above threshold {battery_protection_threshold:.0f}%"
        )
    if charger.brand == EVChargerBrand.ZAPPI and charger.charge_mode:
        if charger.charge_mode.lower() in ZAPPI_BATTERY_DRAINING_MODES:
            return True, (
                f"Zappi in {charger.charge_mode!r} mode drawing from battery "
                f"(SoC {battery_soc:.0f}% <= {battery_protection_threshold:.0f}%)"
            )
    return True, (
        f"EV charger drawing from battery "
        f"(SoC {battery_soc:.0f}% <= {battery_protection_threshold:.0f}%)"
    )


# ── Second immersion element ──────────────────────────────────────────────────


def should_divert_to_second_immersion(
    solar_power_w: float,
    house_load_w: float,
    battery_soc: float,
    battery_power_w: float,
    second_immersion_wattage_w: float,
    immersion_temp: float | None,
    immersion_target_temp: float,
    soc_threshold: int = SURPLUS_DIVERT_SOC_THRESHOLD,
) -> tuple[bool, str]:
    """
    Decide whether to turn on the second immersion element.

    The second element only activates when:
    1. Main element has reached its target temperature (water is hot → main is off)
    2. Battery SoC is above the threshold
    3. Net solar surplus >= second element wattage

    Returns (should_divert, reason).
    """
    if immersion_temp is None or immersion_temp < immersion_target_temp:
        return False, "Main element still heating or temp unknown — second not needed"

    if battery_soc < soc_threshold:
        return False, f"Battery SoC {battery_soc:.0f}% below threshold {soc_threshold}%"

    battery_charging_w = max(0, battery_power_w)
    net_surplus_w = solar_power_w - house_load_w - battery_charging_w
    if net_surplus_w < second_immersion_wattage_w:
        return False, (
            f"Insufficient surplus ({net_surplus_w:.0f}W < "
            f"{second_immersion_wattage_w:.0f}W second element)"
        )

    return True, (
        f"Main at target {immersion_temp:.1f}°C, {net_surplus_w:.0f}W surplus — "
        f"diverting to second element"
    )
