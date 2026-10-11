"""
sunrise_charge.py — the SoC at sunrise with tonight's planned charge.

estimated_soc_at_sunrise (battery.estimate_will_survive_night) projects the battery from now to
sunrise with no charge at all. That is the right input for "will the battery last without a
charge", and it holds at the minimum SoC whenever the battery would run flat. In the evening it
therefore reads the minimum although a charge is planned and the battery ends the night well
above it. This module projects the same night with the planned charge in it:

  1. The battery runs down on the house load from now to the start of the charge window.
  2. The window adds energy, at the charge rate the plan uses, up to the target SoC.
  3. The battery runs down on the house load from the end of the window to sunrise.

The window itself adds no house load: the grid serves the house while the battery charges.

The plan sizes the window for the SoC it is written at, so the window published in the evening
is shorter than the one written at 02:00, when the battery has run down. A window that is not
running yet is therefore sized again for the projected SoC at its start (PlannedCharge.size_window),
which is what the plan writes then. A window that is running is used as it stands.

The projection reads the clock, so the sunrise is the next SOLAR_SUNRISE_HOUR on the clock. That
keeps the figure steady through the day. Any night with no charge in it (a skipped night, no
timed window, a window that is over or starts after sunrise) gives back the figure without a
charge, so the two figures only differ by what the planned charge adds.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, time

from ..const import SOLAR_SUNRISE_HOUR
from .charge_window import ChargeWindow

_MINUTES_PER_DAY = 24 * 60

# The kWh the house uses over a number of minutes starting at a minute of the day. The start
# may run past midnight, so a per-slot profile wraps it.
LoadModel = Callable[[float, float], float]

BASIS_SKIPPED = "No charge planned tonight, so this is the figure without a charge"
BASIS_NO_WINDOW = "No timed charge window, so this is the figure without a charge"
BASIS_NOT_BEFORE_SUNRISE = (
    "The charge window is over or starts after sunrise, so this is the figure without a charge"
)
BASIS_REACHES_TARGET = "The planned charge takes the battery up to the target"
BASIS_RATE_LIMITED = "The charge window ends before the battery reaches the target"
BASIS_RATE_UNKNOWN = "The charge rate is not known, so the battery is assumed to reach the target"
BASIS_ABOVE_TARGET = "The battery is already at the target when the window opens, so none is added"


LOAD_NOTE_PER_SLOT = "Load: the per-slot profile."
LOAD_NOTE_FLAT = "Load: the flat daily average, as there is no per-slot profile yet."

_SLOT_MINUTES = _MINUTES_PER_DAY // 48


def flat_load(hourly_kwh: float) -> LoadModel:
    """The same load every hour, as night survival uses it."""
    return lambda _from_minute, minutes: hourly_kwh * minutes / 60


def slot_load(slots_kwh: list[float]) -> LoadModel:
    """The load of 48 half hour slots, the first starting at midnight, wrapping at midnight."""

    def used(from_minute: float, minutes: float) -> float:
        total, position, left = 0.0, from_minute % _MINUTES_PER_DAY, minutes
        while left > 1e-9:
            to_boundary = _SLOT_MINUTES - position % _SLOT_MINUTES
            span = min(left, to_boundary)
            total += slots_kwh[int(position // _SLOT_MINUTES) % 48] * span / _SLOT_MINUTES
            position, left = (position + span) % _MINUTES_PER_DAY, left - span
        return total

    return used


@dataclass(frozen=True)
class BatteryNow:
    """The battery as it stands, and the figure without a charge used when no charge lands."""

    soc: float
    capacity_kwh: float
    min_soc: float
    soc_without_charge: float


@dataclass(frozen=True)
class PlannedCharge:
    """Tonight's plan as published: the window, the target and the charge rate.

    skipped is a night the plan charges nothing. charge_power_kw is 0.0 when the rate is unknown.
    size_window gives the window the plan writes for a battery at the SoC passed in. Without it
    the published window is used as it is.
    """

    window: ChargeWindow | None
    target_soc: float
    skipped: bool
    charge_power_kw: float = 0.0
    size_window: Callable[[float], ChargeWindow] | None = None


@dataclass(frozen=True)
class SunriseWithCharge:
    """The SoC at sunrise with the plan's charge, and the figures it is made of."""

    soc: float
    soc_at_charge_start: float | None
    charge_added_pct: float
    charge_window: str | None
    basis: str


@dataclass(frozen=True)
class _Timeline:
    """Minutes from now to the start and end of the charge and to sunrise.

    A window that is running now starts at 0 and has its remaining minutes left.
    """

    start: float
    end: float
    sunrise: float
    window_end_minute: float

    @property
    def charges_before_sunrise(self) -> bool:
        return self.start < self.sunrise

    @property
    def charge_minutes(self) -> float:
        return min(self.end, self.sunrise) - self.start


def _minute_of_day(at: datetime) -> float:
    return at.hour * 60 + at.minute + at.second / 60


def _minute_of(at: time) -> int:
    return at.hour * 60 + at.minute


def _timeline(now: datetime, window: ChargeWindow) -> _Timeline:
    """Where the window and sunrise fall, in minutes from now, wrapping midnight."""
    now_minute = _minute_of_day(now)
    start_minute = _minute_of(window.start)
    end_minute = _minute_of(window.end)
    span = (end_minute - start_minute) % _MINUTES_PER_DAY or _MINUTES_PER_DAY
    elapsed = (now_minute - start_minute) % _MINUTES_PER_DAY
    to_start = 0.0 if elapsed < span else (start_minute - now_minute) % _MINUTES_PER_DAY
    to_end = (span - elapsed) if elapsed < span else to_start + span
    sunrise = (SOLAR_SUNRISE_HOUR * 60 - now_minute) % _MINUTES_PER_DAY or _MINUTES_PER_DAY
    return _Timeline(to_start, to_end, sunrise, float(end_minute))


def _pct(kwh: float, capacity_kwh: float) -> float:
    return kwh / capacity_kwh * 100


def _unchanged(battery: BatteryNow, basis: str) -> SunriseWithCharge:
    return SunriseWithCharge(battery.soc_without_charge, None, 0.0, None, basis)


def _soc_at_start(
    battery: BatteryNow, now: datetime, timeline: _Timeline, load: LoadModel
) -> float:
    """The SoC when the window opens, the current SoC when it is running now."""
    if timeline.start <= 0:
        return battery.soc
    used = load(_minute_of_day(now), timeline.start)
    return max(battery.min_soc, battery.soc - _pct(used, battery.capacity_kwh))


def _soc_after_window(
    battery: BatteryNow, plan: PlannedCharge, start: float, minutes: float
) -> tuple[float, str]:
    """The SoC the window reaches and the basis: up to the target, or as far as the rate goes."""
    ceiling = min(plan.target_soc, 100.0)
    if start >= ceiling:
        return start, BASIS_ABOVE_TARGET
    if plan.charge_power_kw <= 0:
        return ceiling, BASIS_RATE_UNKNOWN
    delivered_kwh = plan.charge_power_kw * minutes / 60
    reached = start + _pct(delivered_kwh, battery.capacity_kwh)
    if reached >= ceiling:
        return ceiling, BASIS_REACHES_TARGET
    return reached, BASIS_RATE_LIMITED


def _soc_at_sunrise(
    battery: BatteryNow, timeline: _Timeline, after_window: float, load: LoadModel
) -> float:
    """What the battery has at sunrise after the house load from the window's end."""
    remaining = timeline.sunrise - timeline.end
    if remaining <= 0:
        return after_window
    used = load(timeline.window_end_minute, remaining)
    return max(battery.min_soc, after_window - _pct(used, battery.capacity_kwh))


def project_sunrise_with_charge(
    battery: BatteryNow, now: datetime, plan: PlannedCharge, load: LoadModel
) -> SunriseWithCharge:
    """The SoC at the next sunrise with tonight's planned charge in it.

    Falls back to battery.soc_without_charge when no charge lands before sunrise. A window
    that is running now starts from the current SoC. A target at or below the SoC when the
    window opens adds nothing.
    """
    window = plan.window
    if plan.skipped or window is None:
        return _unchanged(battery, BASIS_SKIPPED if plan.skipped else BASIS_NO_WINDOW)
    timeline = _timeline(now, window)
    if not timeline.charges_before_sunrise:
        return _unchanged(battery, BASIS_NOT_BEFORE_SUNRISE)
    start = _soc_at_start(battery, now, timeline, load)
    if timeline.start > 0 and plan.size_window is not None:
        window = plan.size_window(start)
        timeline = _timeline(now, window)
    after_window, basis = _soc_after_window(battery, plan, start, timeline.charge_minutes)
    return SunriseWithCharge(
        soc=_soc_at_sunrise(battery, timeline, after_window, load),
        soc_at_charge_start=start,
        charge_added_pct=after_window - start,
        charge_window=window.text,
        basis=basis,
    )


def with_load_note(projection: SunriseWithCharge, note: str) -> SunriseWithCharge:
    """The projection with its basis saying which load it used (LOAD_NOTE_*).

    A night with no charge in it is the figure without a charge, which always reads the flat
    load, so it is left as it is.
    """
    if projection.charge_window is None:
        return projection
    return replace(projection, basis=f"{projection.basis}. {note}")
