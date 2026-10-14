"""
window_guard.py: is the charge window on the inverter inside the cheap hours?

The manager writes slot 1 for the cheap rate period. Anything else can change it afterwards: a
tap in the Home Assistant app, GivTCP's own schedule or the GivEnergy app. A window that runs
into the day rate charges the battery at the day rate, and the written plan never says so.

This reads the window the inverter holds and says whether to put it back. It acts only when
all of these hold:

  - the manager has written to the inverter before, so a schedule a user set up first is left
    alone,
  - a manual charge or skip override is not on,
  - the window is not unused and covers at least one minute that is not below the base rate,
  - the window has not been put back REPLAN_MAX_WRITES times already today.

What to write is the window the plan wants, the same one tonight's write uses. The charge
target is left as it is.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time

from ..const import REPLAN_MAX_WRITES
from .charge_window import window_stays_cheap
from .tariff import TariffConfig
from .write_log import WINDOW_REPAIR_REASON, is_manager_write


@dataclass
class GuardState:
    """What the coordinator remembers between cycles: one repair at a time, and the last try."""

    pending: bool = False
    last_try: datetime | None = None
    reported: str = ""


@dataclass(frozen=True)
class WindowRepair:
    """The window to write, and the line that goes into the log."""

    start: time
    end: time
    note: str


@dataclass(frozen=True)
class GuardInputs:
    """What the decision needs from the inverter, the plan and the write log."""

    tariff: TariffConfig
    live_start: time | None
    live_end: time | None
    planned_start: time
    planned_end: time
    override_active: bool
    log: Iterable[Mapping[str, object]]
    entity_id: str
    today: date


def parse_clock(text: object) -> time | None:
    """An HH:MM or HH:MM:SS clock time, or None for anything else."""
    try:
        return time.fromisoformat(str(text).strip())
    except ValueError:
        return None


def manager_has_written(log: Iterable[Mapping[str, object]]) -> bool:
    """True once the manager has sent any write to the inverter."""
    return any(is_manager_write(entry) for entry in log)


def repairs_today(log: Iterable[Mapping[str, object]], entity_id: str, today: date) -> int:
    """How many times the window was put back on this local date."""
    count = 0
    for entry in log:
        if entry.get("reason") != WINDOW_REPAIR_REASON or entry.get("entity_id") != entity_id:
            continue
        try:
            when = datetime.fromisoformat(str(entry.get("time")))
        except ValueError:
            continue
        count += when.date() == today
    return count


def decide_repair(inputs: GuardInputs) -> WindowRepair | None:
    """The window to write back, or None when the one on the inverter is fine or not ours."""
    start, end = inputs.live_start, inputs.live_end
    if start is None or end is None or inputs.override_active:
        return None
    if window_stays_cheap(inputs.tariff, start, end):
        return None
    log = list(inputs.log)
    if not manager_has_written(log):
        return None
    if repairs_today(log, inputs.entity_id, inputs.today) >= REPLAN_MAX_WRITES:
        return None
    planned = f"{inputs.planned_start:%H:%M} to {inputs.planned_end:%H:%M}"
    was = f"{start:%H:%M} to {end:%H:%M}"
    note = f"the window was {was}, past the cheap rate, set back to {planned}"
    return WindowRepair(inputs.planned_start, inputs.planned_end, note)
