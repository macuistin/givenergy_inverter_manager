"""
planned_heating.py: what the scheduled immersion heating plans, in a sentence.

It reads the ready plan (immersion_ready.py) and the cheapest window (immersion_window.py) and
changes neither. The sentence says one of these things:

  * the cheap window is heating the water now,
  * the water is ready for the next ready time and no heating is planned, with the next window
    that could heat it if it cools,
  * the plan heats now for the next ready time,
  * the plan heats later for the next ready time, from when to when and at which rate.

With no ready time the sentence covers the cheap window alone. The water counts as ready when it
is at or above the temperature the immersion restarts at, or the run would be under 5 minutes
(WaterReading.needs_heating), the same test the oil start uses. The immersion itself may still
add a few minutes just before a ready time to reach the exact target.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from .immersion_ready import (
    HeatingSpan,
    ReadyInputs,
    next_ready_at,
    place_hours,
    plan_ready,
)
from .immersion_window import WindowOpening, next_window_opening
from .oil_start import WaterReading
from .tariff import TariffConfig

_NO_READY_TIME = "No ready time is set."
_NOTHING_PLANNED = "No heating planned: no ready time is set and the tariff has no cheaper slot."
_TOMORROW = " tomorrow"


@dataclass(frozen=True)
class PlanQuery:
    """What the sentence reads. times are the ready times, empty when none is set."""

    tariff: TariffConfig
    now: datetime
    times: tuple[time, ...]
    water: WaterReading
    heater_on: bool = False


def _tomorrow(moment: datetime, now: datetime) -> str:
    return "" if moment.date() == now.date() else _TOMORROW


def _ready_label(ready_at: datetime, now: datetime) -> str:
    if ready_at.date() == now.date():
        return f"the {ready_at:%H:%M} ready time"
    return f"tomorrow's {ready_at:%H:%M} ready time"


def _water_text(water: WaterReading) -> str:
    return f"water {water.temp:.1f}°C"


def _span_between(span: HeatingSpan, now: datetime) -> str:
    band = f"at the {span.name} rate"
    return f"{span.start:%H:%M} to {span.end:%H:%M}{_tomorrow(span.start, now)} {band}"


def _span_until(span: HeatingSpan, now: datetime) -> str:
    return f"until {span.end:%H:%M}{_tomorrow(span.end, now)} at the {span.name} rate"


def _spans_text(spans: list[HeatingSpan], now: datetime) -> str:
    return " and ".join(_span_between(span, now) for span in spans)


def _spans_text_now(spans: list[HeatingSpan], now: datetime) -> str:
    """The same, with the first span running from now."""
    first, rest = _span_until(spans[0], now), spans[1:]
    return " and ".join([first, *(_span_between(span, now) for span in rest)])


def _window_heating_now(query: PlanQuery, opening: WindowOpening | None) -> bool:
    """The cheap window is open and the immersion rule heats in it.

    A fresh start needs the water below the restart threshold. A heater that is on carries on
    to the target.
    """
    if opening is None or not opening.is_open:
        return False
    water = query.water
    return water.temp < (water.target if query.heater_on else water.restart_below)


def _window_now_sentence(query: PlanQuery, opening: WindowOpening) -> str:
    water = query.water
    return (
        f"Heating now in the {opening.name} slot until "
        f"{opening.end:%H:%M}{_tomorrow(opening.end, query.now)} "
        f"({_water_text(water)}, target {water.target:.0f}°C)."
    )


def _window_sentence(query: PlanQuery, opening: WindowOpening) -> str:
    """The cheap window as a possible heating time."""
    below = f"only if the water is below {query.water.restart_below:g}°C"
    slot = f"{opening.start:%H:%M} to {opening.end:%H:%M} slot"
    if opening.is_open:
        return f"The {slot} is open now, heating {below}."
    return f"Next possible heating: {slot}{_tomorrow(opening.start, query.now)}, {below} by then."


def _ready_inputs(query: PlanQuery) -> ReadyInputs:
    water = query.water
    return ReadyInputs(
        query.tariff,
        query.now,
        query.times,
        water.temp,
        water.target,
        water.rate_c_per_h,
        query.heater_on,
    )


def _heating_sentence(query: PlanQuery, ready_at: datetime) -> str:
    """The plan for a ready time the water will not reach on its own."""
    water, now = query.water, query.now
    plan = plan_ready(_ready_inputs(query))
    placed = place_hours(query.tariff, now, ready_at, plan.hours_needed)
    if not plan.heat_now:
        text = _spans_text(placed.spans, now)
        return f"Heating planned for {_ready_label(ready_at, now)}: {text}."
    text = _spans_text_now(placed.spans, now)
    lead = f"Heating now to be ready by {ready_at:%H:%M} ({_water_text(water)}, "
    sentence = f"{lead}target {water.target:.0f}°C): {text}."
    late = "" if plan.expected_ready else " The water will not be fully ready by then."
    return sentence + late


def _ready_sentence(query: PlanQuery, ready_at: datetime, opening: WindowOpening | None) -> str:
    water = query.water
    if water.needs_heating:
        return _heating_sentence(query, ready_at)
    label = _ready_label(ready_at, query.now)
    ready = f"No heating planned for {label} ({_water_text(water)}, ready)."
    return ready if opening is None else f"{ready} {_window_sentence(query, opening)}"


def _without_ready_time(query: PlanQuery, opening: WindowOpening | None) -> str:
    if opening is None:
        return _NOTHING_PLANNED
    return f"{_NO_READY_TIME} {_window_sentence(query, opening)}"


def describe_planned_heating(query: PlanQuery) -> str:
    """What the scheduled heating plans for the water, in plain words."""
    opening = next_window_opening(query.tariff, query.now)
    if opening is not None and _window_heating_now(query, opening):
        return _window_now_sentence(query, opening)
    ready_at = next_ready_at(query.now, query.times)
    if ready_at is None:
        return _without_ready_time(query, opening)
    return _ready_sentence(query, ready_at, opening)
