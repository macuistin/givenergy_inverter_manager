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
    average hourly consumption, and hours until sunrise. While the battery is paused
    (core/battery_pause.py) the grid serves the house, so those hours add no consumption.
    night_estimate() works out the figures and survival_reason() puts them in words, so the
    engine can quote the published figure after it is paced.

  survival_attributes()
    Says in words why night survival is Safe, Warning or Critical, with the
    numbers behind it, and in plain phrases for the dashboard. Shown in the attributes
    of the Battery Overnight Confidence sensor. While tonight's planned charge counts, the
    phrases also give the figure with it and say whether it covers a tight or short night.

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
from .battery_pause import PauseWindow, with_note


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


def battery_cost_prompt_due(battery_cost: float, stats: BatteryStats, today: date) -> bool:
    """True when the battery cost is still unset after the integration has run for a while.

    With no cost, battery wear is 0 and the net saving equals the saving against the grid.
    "A while" is the same number of days the battery life estimate waits for.
    """
    return battery_cost <= 0 and stats.days_tracked(today) >= BATTERY_LIFE_ESTIMATE_MIN_DAYS


def calculate_cycle_increment(soc_delta: float) -> float:
    """
    Calculate the cycle increment for a given SoC change.

    A full 100% discharge = 1.0 cycle; a 50% discharge = 0.5 cycles.
    Only a falling SoC counts, which matches the equivalent full cycle count
    a battery BMS reports. A rising SoC adds nothing.
    """
    return max(0.0, -soc_delta) / 100.0


def night_window(hour: int, solar_power_w: float) -> tuple[int, float]:
    """The window the battery must cover before solar starts: (start minute of the day, hours).

    Night survival and the overnight charge skip use this one window, so they cannot disagree
    about how long "the night" is. Solar counts as generating from SOLAR_NOISE_FLOOR_W up, the
    same floor the energy accumulator uses.

      Before sunrise          — from this hour to SOLAR_SUNRISE_HOUR.
      After sunrise, solar on — tonight's pre-solar window, 00:00 to SOLAR_SUNRISE_HOUR,
                                the same window the charge plan models. Today's remaining
                                daylight is not a night hour.
      After sunrise, solar off — from this hour to tomorrow's sunrise.
    """
    if hour < SOLAR_SUNRISE_HOUR:
        return hour * 60, float(max(1, SOLAR_SUNRISE_HOUR - hour))
    if solar_power_w >= SOLAR_NOISE_FLOOR_W:
        return 0, float(SOLAR_SUNRISE_HOUR)
    return hour * 60, float((24 - hour) + SOLAR_SUNRISE_HOUR)


def hours_until_solar(hour: int, solar_power_w: float) -> float:
    """Hours of load the battery must cover before tomorrow's solar starts (see night_window)."""
    return night_window(hour, solar_power_w)[1]


@dataclass(frozen=True)
class PausedNight:
    """A pause window and how many hours of the night window it covers."""

    window: PauseWindow
    hours: float


def paused_night(pause: PauseWindow | None, hour: int, solar_power_w: float) -> PausedNight | None:
    """The pause as it falls in the night window, None when there is none or it misses the night."""
    if pause is None:
        return None
    start_minute, hours = night_window(hour, solar_power_w)
    covered = pause.paused_hours(start_minute, hours)
    return PausedNight(pause, covered) if covered > 0 else None


@dataclass(frozen=True)
class NightEstimateInputs:
    """What the night survival estimate is worked out from."""

    current_soc: float
    battery_capacity_kwh: float
    min_soc: float
    hours_until_solar: float
    average_hourly_consumption_kwh: float
    paused: PausedNight | None = None


@dataclass(frozen=True)
class NightEstimate:
    """The calculated night survival estimate, before any words are put to it.

    soc is the SoC left at sunrise, never below the minimum. shortfall_kwh is how far the
    battery falls short of the night, 0 when it lasts. pause is the pause in the night window.
    """

    will_survive: bool
    soc: float
    shortfall_kwh: float
    pause: PauseWindow | None = None


def night_estimate(inputs: NightEstimateInputs) -> NightEstimate:
    """Work out whether the battery lasts until solar starts. Paused hours add no load."""
    min_soc = inputs.min_soc
    capacity_kwh = inputs.battery_capacity_kwh
    usable_kwh = capacity_kwh * ((inputs.current_soc - min_soc) / 100)
    paused_hours = inputs.paused.hours if inputs.paused else 0.0
    served_hours = max(0.0, inputs.hours_until_solar - paused_hours)
    expected_consumption = served_hours * inputs.average_hourly_consumption_kwh
    remaining_kwh = usable_kwh - expected_consumption
    remaining_soc = (remaining_kwh / capacity_kwh * 100) + min_soc
    window = inputs.paused.window if inputs.paused else None
    if remaining_kwh >= 0:
        return NightEstimate(True, max(min_soc, remaining_soc), 0.0, window)
    return NightEstimate(False, min_soc, abs(remaining_kwh), window)


def survival_reason(estimate: NightEstimate, published_soc: float) -> str:
    """The reason for the estimate, quoting the SoC at sunrise as the sensor publishes it.

    The published figure follows the calculated one at the battery's pace
    (core/sunrise_hold.py), so the words quote it and agree with the sensor. A shortfall is
    the calculated one, so it shows at once.
    """
    if estimate.will_survive:
        reason = (
            "Battery should last until solar. "
            f"Estimated SoC at sunrise: {round(published_soc)}%"
        )
    else:
        reason = (
            "Battery may run low. "
            f"Estimated shortfall: {estimate.shortfall_kwh:.1f}kWh before solar starts."
        )
    return with_note(reason, estimate.pause)


def estimate_will_survive_night(inputs: NightEstimateInputs) -> tuple[bool, float, str]:
    """
    Estimate whether the battery will last until solar starts tomorrow.

    The hours the battery is paused add no consumption, and the reason says so. The reason
    quotes the calculated figure. The engine quotes the published one instead (survival_reason).

    Returns (will_survive, estimated_soc_at_sunrise, reason)
    """
    estimate = night_estimate(inputs)
    return estimate.will_survive, estimate.soc, survival_reason(estimate, estimate.soc)


@dataclass(frozen=True)
class SurvivalReport:
    """The night survival estimate together with the figures it is explained from.

    estimated_soc is the figure without a charge, which the verdict is made on.
    soc_with_charge is the figure with tonight's planned charge, set only while a planned
    charge counts. It changes the words, never the verdict. pause is the battery pause that
    falls in the night, set only while one does. It is named in the words once.
    """

    will_survive: bool
    estimated_soc: float
    min_soc: float
    current_soc: float
    reason: str
    soc_with_charge: float | None = None
    pause: PauseWindow | None = None


# What each level means for tonight, as a person would say it.
OUTLOOK_SAFE = "Lasts the night"
OUTLOOK_WARNING = "Only just lasts the night"
OUTLOOK_CRITICAL = "May run low"


def _outlook(report: SurvivalReport) -> str:
    """Whether the battery lasts until solar starts, as a short phrase."""
    if not report.will_survive:
        return OUTLOOK_CRITICAL
    if report.estimated_soc < report.min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT:
        return OUTLOOK_WARNING
    return OUTLOOK_SAFE


def _charge_figure(report: SurvivalReport) -> float | None:
    """The figure with tonight's charge, when it differs from the one without a charge.

    Both are quoted as whole percentages, so a charge that adds less than a point says nothing.
    """
    with_charge = report.soc_with_charge
    if with_charge is None or round(with_charge) <= round(report.estimated_soc):
        return None
    return with_charge


def _charge_covers(report: SurvivalReport, with_charge: float) -> bool:
    """Whether the figure with the charge is clear of the warning margin."""
    return with_charge >= report.min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT


def _summary(report: SurvivalReport, outlook: str) -> str:
    """The outlook and the expected charge at sunrise. A battery that runs out has no figure.

    When a planned charge counts, both figures are given, and a Warning or May run low says
    whether the charge covers it. A pause that falls in the night is named after them.
    """
    return _with_pause_tag(_summary_figures(report, outlook), report)


def _with_pause_tag(summary: str, report: SurvivalReport) -> str:
    if report.pause is None:
        return summary
    return f"{summary} · battery paused {report.pause.text}"


def _summary_figures(report: SurvivalReport, outlook: str) -> str:
    with_charge = _charge_figure(report)
    if with_charge is not None:
        return _summary_with_charge(report, outlook, with_charge)
    if outlook == OUTLOOK_CRITICAL:
        return outlook
    return f"{outlook} · {report.estimated_soc:.0f}% at sunrise"


def _summary_with_charge(report: SurvivalReport, outlook: str, with_charge: float) -> str:
    """The summary of a night with a planned charge in it."""
    if outlook == OUTLOOK_SAFE:
        return (
            f"{outlook} · {report.estimated_soc:.0f}% at sunrise without a charge, "
            f"about {with_charge:.0f}% with tonight's charge"
        )
    if _charge_covers(report, with_charge):
        return (
            f"{outlook} without a charge · tonight's charge covers it, "
            f"about {with_charge:.0f}% at sunrise"
        )
    return f"{outlook}, even with tonight's charge · about {with_charge:.0f}% at sunrise"


def _sentence(text: str) -> str:
    """The text as a sentence that ends in a full stop."""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _near_minimum(report: SurvivalReport) -> str:
    """How close the figure without a charge is to the minimum SoC."""
    return f"within {NIGHT_SURVIVAL_WARNING_MARGIN_PCT:g} points of the {report.min_soc:g}% minimum"


def _survival_explanation(report: SurvivalReport) -> str:
    """The explanation, with the pause sentence in it once while a pause falls in the night."""
    return with_note(_explanation_text(report), report.pause)


def _explanation_text(report: SurvivalReport) -> str:
    outlook = _outlook(report)
    with_charge = _charge_figure(report)
    if with_charge is not None:
        return _explanation_with_charge(report, outlook, with_charge)
    if outlook == OUTLOOK_WARNING:
        return (
            "The battery should last until solar starts, but only just. "
            f"It is expected to reach about {report.estimated_soc:.0f}% at sunrise, "
            f"{_near_minimum(report)}."
        )
    return report.reason


def _charge_verdict(report: SurvivalReport, with_charge: float) -> str:
    """Whether tonight's planned charge covers the risk, in one sentence."""
    if _charge_covers(report, with_charge):
        return f"Tonight's planned charge covers this: about {with_charge:.0f}% at sunrise."
    return f"Tonight's planned charge does not cover this: about {with_charge:.0f}% at sunrise."


def _explanation_with_charge(report: SurvivalReport, outlook: str, with_charge: float) -> str:
    """The explanation of a night with a planned charge in it: both figures, then the cover."""
    without = f"{report.estimated_soc:.0f}%"
    if outlook == OUTLOOK_SAFE:
        return (
            "The battery should last until solar starts. "
            f"It is expected to reach about {without} at sunrise without a charge, "
            f"and about {with_charge:.0f}% with tonight's planned charge."
        )
    if outlook == OUTLOOK_WARNING:
        return (
            "The battery should last until solar starts, but only just. "
            f"Without a charge it is expected to reach about {without} at sunrise, "
            f"{_near_minimum(report)}. {_charge_verdict(report, with_charge)}"
        )
    return f"{_sentence(report.reason)} {_charge_verdict(report, with_charge)}"


def survival_attributes(report: SurvivalReport) -> dict[str, Any]:
    """Explain the night survival level and give the numbers it comes from.

    Critical: the battery runs out before solar starts. Warning: it lasts, but is
    expected to end within the warning margin of the minimum SoC. Safe: otherwise.
    All three are judged on the night without a charge. While a planned charge counts, the
    summary and the explanation also give the figure with it and say whether it covers a
    Warning or Critical night.
    """
    outlook = _outlook(report)
    return {
        "outlook": outlook,
        "summary": _summary(report, outlook),
        "explanation": _survival_explanation(report),
        "battery_soc": round(report.current_soc, 1),
        "estimated_soc_at_sunrise": round(report.estimated_soc, 1),
        "minimum_soc": report.min_soc,
        "warning_below_soc": report.min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
    }
