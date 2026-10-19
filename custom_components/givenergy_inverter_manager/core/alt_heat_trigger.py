"""
alt_heat_trigger.py: the two moments when the alternative heating is worth switching on.

The water heating advice (alt_heat_advice.py) says what to do. Each trigger here turns one reason
to act into a state an automation can trigger on. They are separate, because they answer
different questions:

  * The ready-by trigger announces the start for a ready time. The start is just in time: the
    ready time less the run the water needs to reach the target. The water counts as needing heat
    as soon as it is ALT_HEAT_TRIGGER_MARGIN_C below the target, and the start comes earlier the
    further the water is from it, because the run is longer.
  * The low water trigger keeps the immersion from restarting. It fires from
    ALT_HEAT_TRIGGER_MARGIN_C above the lower boundary, the point where the immersion would top
    the water up, while the alternative is the cheaper heat.

Each is idle or start_now. A trigger is a state and nothing more. It sends no alert and never
switches the alternative system or the immersion. What to do on a change of state is the user's
automation. See docs/automations.md.

A trigger that has fired holds start_now until the water reaches the target. Water that hovers
at the threshold would otherwise flip the state on every reading. The hold ends at once if the
alternative stops being the cheaper heat, and the ready-by hold ends with its ready time.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..const import ALT_HEAT_TRIGGER_MARGIN_C
from .alt_heat_advice import AdviceInputs, WaterHeatingAdvice
from .alt_heat_start import (
    StartQuery,
    WaterReading,
    low_water_minutes,
    suggest_alt_heat_start,
)
from .immersion_ready import next_ready_at
from .timeutil import elapsed_seconds

STATE_IDLE = "idle"
STATE_START_NOW = "start_now"
STATES = (STATE_IDLE, STATE_START_NOW)


@dataclass(frozen=True)
class AltHeatTrigger:
    """The state, and what a run would be: its length, when it was due and what it saves.

    The figures are None while idle. run_minutes is also None when the heating rate is not
    known. start_by and ready_at are set by the ready-by trigger only.
    """

    state: str = STATE_IDLE
    run_minutes: int | None = None
    start_by: datetime | None = None
    ready_at: datetime | None = None
    saving_per_kwh: float | None = None


@dataclass
class HeldTriggers:
    """What each trigger said last cycle, so a trigger that fired holds until the water is warm."""

    ready_by: AltHeatTrigger = field(default_factory=AltHeatTrigger)
    low_water: AltHeatTrigger = field(default_factory=AltHeatTrigger)


def ready_by_trigger(
    inputs: AdviceInputs, previous: AltHeatTrigger | None = None
) -> AltHeatTrigger:
    """start_now once the start for the next ready time is due, else idle.

    It needs a water reading, a ready time and the immersion's scheduled heating, which is the
    backstop if the alternative is not started. The start is the ready time less the run the
    water needs, so the water is at the target when it is wanted. Once start_now, it holds for
    the same ready time until the water reaches the target.
    """
    ready = next_ready_at(inputs.now, inputs.ready_times)
    if inputs.water is None or not inputs.scheduled_heating or ready is None:
        return AltHeatTrigger()
    holding = _holds_for(previous, inputs.water, ready)
    start = suggest_alt_heat_start(_start_query(inputs, holding=holding), ready)
    if start is None or start.start_by is None:
        return AltHeatTrigger()
    start_by = start.start_by
    if holding or elapsed_seconds(inputs.now, start_by) <= 0:
        return AltHeatTrigger(
            STATE_START_NOW, start.run_minutes, start_by, start.ready_at, start.saving_per_kwh
        )
    return AltHeatTrigger()


def low_water_trigger(
    advice: WaterHeatingAdvice | None,
    inputs: AdviceInputs,
    previous: AltHeatTrigger | None = None,
) -> AltHeatTrigger:
    """start_now while the water is near the lower boundary and the alternative is cheaper.

    Solar surplus that is heating the water needs no other heat, so it leaves this idle. Once
    start_now, it holds until the water reaches the target, so long as the alternative is still
    cheaper.
    """
    water = inputs.water
    if advice is None or water is None or inputs.solar_surplus:
        return AltHeatTrigger()
    if advice.alt_cost_per_kwh >= advice.electricity_cost_per_kwh:
        return AltHeatTrigger()
    minutes = low_water_minutes(
        water, advice.electricity_cost_per_kwh, advice.alt_cost_per_kwh, ALT_HEAT_TRIGGER_MARGIN_C
    )
    if minutes is not None:
        return AltHeatTrigger(STATE_START_NOW, minutes, None, None, advice.alt_saving_per_kwh)
    return previous if _holds(previous, water) and previous is not None else AltHeatTrigger()


def _start_query(inputs: AdviceInputs, *, holding: bool) -> StartQuery:
    solar = inputs.tariff.export_rate if inputs.solar_surplus else None
    return StartQuery(
        inputs.tariff,
        inputs.now,
        inputs.water,
        inputs.alt_cost_per_kwh,
        solar,
        lift_below_target_c=ALT_HEAT_TRIGGER_MARGIN_C,
        holding=holding,
    )


def _holds(previous: AltHeatTrigger | None, water: WaterReading) -> bool:
    """A trigger that fired last cycle and whose water is not yet at the target."""
    return previous is not None and previous.state == STATE_START_NOW and water.temp < water.target


def _holds_for(previous: AltHeatTrigger | None, water: WaterReading, ready: datetime) -> bool:
    """Like _holds, for the same ready time: a new ready time starts from idle."""
    return _holds(previous, water) and previous is not None and previous.ready_at == ready
