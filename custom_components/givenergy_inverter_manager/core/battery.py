"""
battery.py — Battery health, cycle tracking, and night-survival estimation.

Provides:
  BatteryStats        — aggregated lifetime stats: cycle count, charge history,
                        last full-charge date, estimated remaining life, and
                        projected years remaining based on average daily usage.
                        Rated cycles default to BATTERY_RATED_CYCLES (const.py).

  calculate_cycle_increment()
    Converts an SoC delta (%) into a fractional cycle count. One cycle is the
    battery's full capacity discharged once (equivalent full cycle), so only a
    falling SoC counts. A 100% fall equals 1.0 cycle; partial falls are
    proportional.

  estimate_will_survive_night()
    Predicts whether the battery will last until solar generation starts
    tomorrow morning, given current SoC, capacity, minimum SoC floor,
    average hourly consumption, and hours until sunrise.

  survival_attributes()
    Says in words why night survival is Safe, Warning or Critical, with the
    numbers behind it. Shown in the attributes of the Night Survival Confidence
    sensor.

Note: BatterySession tracking (per-session energy, depth-of-discharge,
round-trip efficiency) is planned for v0.2.0 when energy accumulation is
persisted across HA restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# GivEnergy battery typical rated cycles
from ..const import (
    BATTERY_LIFE_ESTIMATE_MIN_DAYS,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
    SOLAR_NOISE_FLOOR_W,
    SOLAR_SUNRISE_HOUR,
)
from ..const import BATTERY_RATED_CYCLES as TYPICAL_RATED_CYCLES


@dataclass
class BatteryStats:
    """Aggregated battery statistics."""
    total_cycles: float = 0.0
    last_full_charge_date: date | None = None
    tracking_start_date: date | None = None
    tracking_start_cycles: float = 0.0
    lifetime_from_bms: bool = False

    @property
    def estimated_remaining_life_pct(self) -> float:
        """Estimate remaining battery life as percentage of rated cycles."""
        return max(0.0, (1 - self.total_cycles / TYPICAL_RATED_CYCLES) * 100)

    def days_since_full_charge_on(self, today: date) -> int | None:
        if self.last_full_charge_date is None:
            return None
        return (today - self.last_full_charge_date).days

    @property
    def days_since_full_charge(self) -> int | None:
        """Days since the last full charge, counted to the wall-clock date.

        Sensors read this at state-write time, where no date can be passed in. Logic
        that has a date uses days_since_full_charge_on.
        """
        return self.days_since_full_charge_on(date.today())

    def days_tracked(self, today: date) -> int:
        """Whole days since cycle tracking started, 0 if it has not started."""
        if self.tracking_start_date is None:
            return 0
        return max(0, (today - self.tracking_start_date).days)

    def average_daily_cycles(self, today: date) -> float:
        """Average cycles per day since tracking started, 0.0 before any data."""
        if self.tracking_start_date is None:
            return 0.0
        cycles = max(0.0, self.total_cycles - self.tracking_start_cycles)
        return cycles / max(1, self.days_tracked(today))

    def estimated_years_remaining(self, today: date) -> float:
        """Estimated years of life remaining based on average daily cycle rate."""
        average_daily_cycles = self.average_daily_cycles(today)
        if average_daily_cycles == 0:
            return 0.0
        remaining_cycles = max(0.0, TYPICAL_RATED_CYCLES - self.total_cycles)
        return remaining_cycles / (average_daily_cycles * 365)

    def years_remaining_estimate(self, today: date) -> float | None:
        """Years of life left, or None until enough days of cycle data exist."""
        if (
            self.days_tracked(today) < BATTERY_LIFE_ESTIMATE_MIN_DAYS
            or self.average_daily_cycles(today) <= 0
        ):
            return None
        return self.estimated_years_remaining(today)


def calculate_cycle_increment(soc_delta: float) -> float:
    """
    Calculate the cycle increment for a given SoC change.

    A full 100% discharge = 1.0 cycle; a 50% discharge = 0.5 cycles.
    Only a falling SoC counts, which matches the equivalent full cycle count
    a battery BMS reports. A rising SoC adds nothing.
    """
    return max(0.0, -soc_delta) / 100.0


def hours_until_solar(hour: int, solar_power_w: float) -> float:
    """
    Hours of load the battery must cover before tomorrow's solar starts.

    Night survival and the overnight charge skip use this one window, so they
    cannot disagree about how long "the night" is. Solar counts as generating
    from SOLAR_NOISE_FLOOR_W up, the same floor the energy accumulator uses.

      Before sunrise          — the hours left until SOLAR_SUNRISE_HOUR.
      After sunrise, solar on — tonight's pre-solar window, SOLAR_SUNRISE_HOUR hours,
                                the same 00:00 to sunrise window the charge plan models.
                                Today's remaining daylight is not a night hour.
      After sunrise, solar off — from now to tomorrow's sunrise.
    """
    if hour < SOLAR_SUNRISE_HOUR:
        return float(max(1, SOLAR_SUNRISE_HOUR - hour))
    if solar_power_w >= SOLAR_NOISE_FLOOR_W:
        return float(SOLAR_SUNRISE_HOUR)
    return float((24 - hour) + SOLAR_SUNRISE_HOUR)


@dataclass(frozen=True)
class NightEstimateInputs:
    """What the night survival estimate is worked out from."""

    current_soc: float
    battery_capacity_kwh: float
    min_soc: float
    hours_until_solar: float
    average_hourly_consumption_kwh: float


def estimate_will_survive_night(inputs: NightEstimateInputs) -> tuple[bool, float, str]:
    """
    Estimate whether the battery will last until solar starts tomorrow.

    Returns (will_survive, estimated_soc_at_sunrise, reason)
    """
    min_soc = inputs.min_soc
    capacity_kwh = inputs.battery_capacity_kwh
    usable_kwh = capacity_kwh * ((inputs.current_soc - min_soc) / 100)
    expected_consumption = inputs.hours_until_solar * inputs.average_hourly_consumption_kwh
    remaining_kwh = usable_kwh - expected_consumption
    remaining_soc = (remaining_kwh / capacity_kwh * 100) + min_soc

    if remaining_kwh >= 0:
        return (
            True,
            max(min_soc, remaining_soc),
            f"Battery should last until solar. Estimated SoC at sunrise: {remaining_soc:.0f}%"
        )
    shortfall_kwh = abs(remaining_kwh)
    return (
        False,
        min_soc,
        f"Battery may run low. Estimated shortfall: {shortfall_kwh:.1f}kWh before solar starts."
    )


@dataclass(frozen=True)
class SurvivalReport:
    """The night survival estimate together with the figures it is explained from."""

    will_survive: bool
    estimated_soc: float
    min_soc: float
    current_soc: float
    reason: str


def _survival_explanation(report: SurvivalReport) -> str:
    margin = NIGHT_SURVIVAL_WARNING_MARGIN_PCT
    if not report.will_survive:
        return f"Critical. {report.reason}"
    if report.estimated_soc < report.min_soc + margin:
        return (
            "Warning. The battery should last until solar starts, but only just. "
            f"It is expected to reach about {report.estimated_soc:.0f}% at sunrise, "
            f"within {margin:g} points of the {report.min_soc:g}% minimum."
        )
    return f"Safe. {report.reason}"


def survival_attributes(report: SurvivalReport) -> dict[str, Any]:
    """Explain the night survival level and give the numbers it comes from.

    Critical: the battery runs out before solar starts. Warning: it lasts, but is
    expected to end within the warning margin of the minimum SoC. Safe: otherwise.
    """
    return {
        "explanation": _survival_explanation(report),
        "battery_soc": round(report.current_soc, 1),
        "estimated_soc_at_sunrise": round(report.estimated_soc, 1),
        "minimum_soc": report.min_soc,
        "warning_below_soc": report.min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
    }
