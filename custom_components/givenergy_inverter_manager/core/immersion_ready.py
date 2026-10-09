"""
immersion_ready.py: plan the heating that has the water at its target by a ready time.

The user lists the times the hot water has to be at the target temperature, for example a
morning and an evening shower. For the next ready time this module works out how long the
heater has to run, then places that time in the cheapest rate bands left before it:

  1. Hours needed = (target - temperature) / heating rate, stretched by CHARGE_WINDOW_MARGIN.
  2. The time between now and the ready time is cut at every tariff boundary into segments,
     each with its import rate.
  3. The hours are filled into the cheapest segments first. Where segments cost the same, the
     later one fills first, so grid heating waits and solar surplus gets the day.
  4. Inside the last segment used, the heating sits at its end, so a partly used band is
     entered late. The heater is wanted now when the current segment is used up to its end,
     or when it is already running and would be wanted within the switch cooldown.

The plan is recomputed every cycle from the live temperature, so it follows what actually
happened: solar surplus that heated the water, a device auto-off that cut a run short, or
hot water drawn in between. It never extends into dearer bands than it must. When the hours
needed do not fit before the ready time, every segment is used and the heater runs now.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ..const import CHARGE_WINDOW_MARGIN, IMMERSION_SWITCH_COOLDOWN_MINUTES
from .tariff import TariffConfig
from .timeutil import elapsed_seconds, local_time_on, shift_real

_SECONDS_PER_HOUR = 3600.0
# A segment is used up when less than this is left over, so rounding does not delay the start.
_USED_UP_SECONDS = 30.0
_COOLDOWN_SECONDS = IMMERSION_SWITCH_COOLDOWN_MINUTES * 60.0


@dataclass(frozen=True)
class ReadyPlan:
    """What the ready times ask of the heater right now.

    ready_time is the next ready time, None when none is set or the water cannot be read.
    expected_ready is whether the water will be at the target by then, None when unknown.
    """

    ready_time: time | None = None
    heat_now: bool = False
    expected_ready: bool | None = None
    hours_needed: float = 0.0


@dataclass(frozen=True)
class RateSegment:
    """A stretch of time with one import rate, as the tariff states it (before discount and VAT)."""

    start: datetime
    end: datetime
    rate: float
    name: str = ""

    @property
    def hours(self) -> float:
        return elapsed_seconds(self.start, self.end) / _SECONDS_PER_HOUR


@dataclass(frozen=True)
class HeatingSpan:
    """A stretch of planned heating inside one rate band."""

    start: datetime
    end: datetime
    rate: float
    name: str


def parse_ready_times(raw: object) -> tuple[time, ...]:
    """Ready times from the saved option: a list of "HH:MM" strings. Bad entries are dropped."""
    if not isinstance(raw, (list, tuple)):
        return ()
    parsed = {t for t in (_parse_time(item) for item in raw) if t is not None}
    return tuple(sorted(parsed))


def _parse_time(item: object) -> time | None:
    try:
        hour, minute = str(item).strip().split(":")[:2]
        return time(int(hour), int(minute))
    except ValueError:
        return None


def next_ready_at(now: datetime, times: tuple[time, ...]) -> datetime | None:
    """The soonest moment after *now* that is one of the ready times."""
    if not times:
        return None
    moments = []
    for at in times:
        moment = local_time_on(now, at)
        if elapsed_seconds(now, moment) <= 0:
            moment = local_time_on(now + timedelta(days=1), at)
        moments.append(moment)
    return min(moments, key=lambda m: elapsed_seconds(now, m))


def _boundaries(tariff: TariffConfig, now: datetime, end: datetime) -> list[datetime]:
    """Every tariff boundary strictly between now and the end, in order."""
    points = []
    for period in tariff.rate_periods:
        for at in (period.start, period.end):
            for days in (0, 1):
                moment = local_time_on(now + timedelta(days=days), at)
                if 0 < elapsed_seconds(now, moment) < elapsed_seconds(now, end):
                    points.append(moment)
    return sorted(set(points))


def rate_segments(tariff: TariffConfig, now: datetime, end: datetime) -> list[RateSegment]:
    """The time from now to *end*, cut at every tariff boundary, each piece with its rate."""
    edges = [now, *_boundaries(tariff, now, end), end]
    segments = []
    for seg_start, seg_end in zip(edges, edges[1:], strict=False):
        middle = seg_start + (seg_end - seg_start) / 2
        period = tariff.get_current_rate(middle)
        segments.append(RateSegment(seg_start, seg_end, period.rate, period.name))
    return segments


def _fill_cheapest_first(segments: list[RateSegment], hours: float) -> dict[int, float]:
    """Hours given to each segment (by position), cheapest first and later first on a tie."""
    order = sorted(range(len(segments)), key=lambda i: (segments[i].rate, -i))
    left, given = hours, {}
    for index in order:
        take = min(segments[index].hours, left)
        if take > 0:
            given[index] = take
            left -= take
    return given


@dataclass(frozen=True)
class Placement:
    """Where the heating hours go between now and a ready time.

    segments are the rate segments in order. hours maps a segment's position to the hours the
    plan gives it. The heating sits at the end of a part-used segment.
    """

    segments: list[RateSegment]
    hours: dict[int, float]
    needed: float

    @property
    def fits(self) -> bool:
        return sum(self.hours.values()) >= self.needed - 1e-9

    @property
    def starts_at(self) -> datetime:
        """When the plan first heats: the earliest start among the segments it uses."""
        return min(self._starts())

    @property
    def average_rate(self) -> float:
        """The hours-weighted rate of the plan, as the tariff states it (before discount, VAT)."""
        total = sum(self.hours.values())
        return sum(self.segments[i].rate * h for i, h in self.hours.items()) / total

    @property
    def spans(self) -> list[HeatingSpan]:
        """The planned heating in time order, one span per rate band, neighbours joined."""
        spans: list[HeatingSpan] = []
        for index in sorted(self.hours):
            segment = self.segments[index]
            span = HeatingSpan(self._start_in(index), segment.end, segment.rate, segment.name)
            joined = bool(spans) and spans[-1].end == span.start and spans[-1].name == span.name
            if joined:
                span = HeatingSpan(spans.pop().start, span.end, span.rate, span.name)
            spans.append(span)
        return spans

    def _start_in(self, index: int) -> datetime:
        segment, given = self.segments[index], self.hours[index]
        if given >= segment.hours - 1e-9:
            return segment.start
        return shift_real(segment.end, -timedelta(hours=given))

    def _starts(self) -> list[datetime]:
        return [self._start_in(index) for index in self.hours]


def place_hours(tariff: TariffConfig, now: datetime, ready: datetime, needed: float) -> Placement:
    """Place *needed* heater hours in the cheapest segments between now and the ready time."""
    segments = rate_segments(tariff, now, ready)
    return Placement(segments, _fill_cheapest_first(segments, needed), needed)


def hours_to_heat(temp: float, target: float, rate_c_per_h: float) -> float:
    """Heater hours to lift the water to the target, with the safety margin."""
    if temp >= target or rate_c_per_h <= 0:
        return 0.0
    return (target - temp) / rate_c_per_h * (1 + CHARGE_WINDOW_MARGIN)


@dataclass(frozen=True)
class ReadyInputs:
    """Everything the plan reads. temp is None when the water cannot be read."""

    tariff: TariffConfig
    now: datetime
    times: tuple[time, ...]
    temp: float | None
    target: float
    rate_c_per_h: float
    heater_on: bool = False


def plan_ready(inputs: ReadyInputs) -> ReadyPlan:
    """The plan for the next ready time."""
    now, temp = inputs.now, inputs.temp
    ready = next_ready_at(now, inputs.times)
    if ready is None or temp is None:
        return ReadyPlan()
    needed = hours_to_heat(temp, inputs.target, inputs.rate_c_per_h)
    if needed <= 0:
        return ReadyPlan(ready.timetz().replace(tzinfo=None), False, True, 0.0)
    placed = place_hours(inputs.tariff, now, ready, needed)
    first = placed.segments[0]
    left_in_first = elapsed_seconds(first.start, first.end)
    slack = left_in_first - placed.hours.get(0, 0.0) * _SECONDS_PER_HOUR
    # A run in progress carries on when the plan would start within the switch cooldown. An
    # off now could not be undone in time, because the write cooldown holds the next on back.
    used_up = slack <= _USED_UP_SECONDS or (inputs.heater_on and slack <= _COOLDOWN_SECONDS)
    return ReadyPlan(ready.timetz().replace(tzinfo=None), used_up, placed.fits, needed)
