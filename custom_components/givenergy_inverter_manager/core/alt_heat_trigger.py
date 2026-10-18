"""
alt_heat_trigger.py: the moments when the alternative heating is worth switching on.

The water heating advice (alt_heat_advice.py) already says what to do. This turns the two moments
that call for action into one state an automation can trigger on:

  * start_now: the alternative has to start now for the next ready time, or the immersion will do
    the heating at a dearer rate. It is the ready-by start whose time has come.
  * keep_warm: the water has cooled to the lower boundary, where the immersion is about to top it
    up, and the alternative is cheaper than the grid. A short run lifts it instead.

Anything else is idle. The state is a trigger and nothing more. It sends no alert and never
switches the alternative system or the immersion. What to do on a change of state is the user's
automation. See docs/automations.md.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .alt_heat_advice import WaterHeatingAdvice
from .alt_heat_start import WaterReading, keep_warm_minutes
from .timeutil import elapsed_seconds

STATE_IDLE = "idle"
STATE_KEEP_WARM = "keep_warm"
STATE_START_NOW = "start_now"
STATES = (STATE_IDLE, STATE_KEEP_WARM, STATE_START_NOW)


@dataclass(frozen=True)
class AltHeatTrigger:
    """The state, and what a run would be: its length, when it was due and what it saves.

    run_minutes and saving_per_kwh are None while idle. start_by is the time the start was due,
    set for start_now only.
    """

    state: str = STATE_IDLE
    run_minutes: int | None = None
    start_by: datetime | None = None
    saving_per_kwh: float | None = None


def alt_heat_trigger(
    advice: WaterHeatingAdvice | None, water: WaterReading | None, now: datetime
) -> AltHeatTrigger:
    """The trigger state for this advice. The ready-by start wins over a keep-warm run."""
    if advice is None:
        return AltHeatTrigger()
    start = advice.alt_start
    if start is not None and _is_due(start.start_by, now):
        return AltHeatTrigger(
            STATE_START_NOW, start.run_minutes, start.start_by, start.saving_per_kwh
        )
    if advice.keep_warm is not None and water is not None:
        grid, alt = advice.electricity_cost_per_kwh, advice.alt_cost_per_kwh
        minutes = keep_warm_minutes(water, grid, alt)
        return AltHeatTrigger(STATE_KEEP_WARM, minutes, None, advice.alt_saving_per_kwh)
    return AltHeatTrigger()


def _is_due(start_by: datetime | None, now: datetime) -> bool:
    return start_by is not None and elapsed_seconds(now, start_by) <= 0
