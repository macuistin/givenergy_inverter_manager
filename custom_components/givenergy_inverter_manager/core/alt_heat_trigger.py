"""
alt_heat_trigger.py: the two moments when the alternative heating is worth switching on.

The water heating advice (alt_heat_advice.py) says what to do. Each trigger here turns one reason
to act into a state an automation can trigger on. They are separate, because they answer
different questions:

  * The ready-by trigger announces the start for a ready time. The alternative has to start now
    to lift the water to the target before the immersion would have to. The water counts as
    needing heat as soon as it is ALT_HEAT_TRIGGER_MARGIN_C below the target, and the start comes
    earlier the further the water is from it, because the run is longer.
  * The low water trigger keeps the immersion from restarting. It fires from
    ALT_HEAT_TRIGGER_MARGIN_C above the lower boundary, the point where the immersion would top
    the water up, while the alternative is the cheaper heat.

Each is idle or start_now. A trigger is a state and nothing more. It sends no alert and never
switches the alternative system or the immersion. What to do on a change of state is the user's
automation. See docs/automations.md.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..const import ALT_HEAT_TRIGGER_MARGIN_C
from .alt_heat_advice import AdviceInputs, WaterHeatingAdvice
from .alt_heat_start import AltHeatStart, StartQuery, low_water_minutes, suggest_alt_heat_start
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


def ready_by_trigger(inputs: AdviceInputs) -> AltHeatTrigger:
    """start_now once the start for the next ready time is due, else idle.

    It needs a water reading, a ready time and the immersion's scheduled heating, which is the
    backstop the start relies on. The start is the latest the alternative can begin and still
    finish before the immersion would have to.
    """
    ready = next_ready_at(inputs.now, inputs.ready_times)
    if inputs.water is None or not inputs.scheduled_heating or ready is None:
        return AltHeatTrigger()
    solar = inputs.tariff.export_rate if inputs.solar_surplus else None
    query = StartQuery(
        inputs.tariff,
        inputs.now,
        inputs.water,
        inputs.alt_cost_per_kwh,
        solar,
        lift_below_target_c=ALT_HEAT_TRIGGER_MARGIN_C,
    )
    start = suggest_alt_heat_start(query, ready)
    if start is None or not _is_due(start, inputs.now):
        return AltHeatTrigger()
    return AltHeatTrigger(
        STATE_START_NOW, start.run_minutes, start.start_by, start.ready_at, start.saving_per_kwh
    )


def low_water_trigger(advice: WaterHeatingAdvice | None, inputs: AdviceInputs) -> AltHeatTrigger:
    """start_now while the water is near the lower boundary and the alternative is cheaper.

    Solar surplus that is heating the water needs no other heat, so it leaves this idle.
    """
    water = inputs.water
    if advice is None or water is None or inputs.solar_surplus:
        return AltHeatTrigger()
    minutes = low_water_minutes(
        water, advice.electricity_cost_per_kwh, advice.alt_cost_per_kwh, ALT_HEAT_TRIGGER_MARGIN_C
    )
    if minutes is None:
        return AltHeatTrigger()
    return AltHeatTrigger(STATE_START_NOW, minutes, None, None, advice.alt_saving_per_kwh)


def _is_due(start: AltHeatStart, now: datetime) -> bool:
    return start.start_by is not None and elapsed_seconds(now, start.start_by) <= 0
