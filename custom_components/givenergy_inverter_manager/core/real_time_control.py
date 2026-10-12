"""When GivTCP's Real Time Control setting being off should raise a repair.

GivTCP only sends changes from Home Assistant to the inverter while its Real Time Control
setting is on. With it off, a write is accepted and ignored, so the inverter keeps its old charge
window and target. An upgrade of GivTCP can reset the setting. Pure Python, no Home Assistant
imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# Cycles in a row the switch must read off before a repair appears, so a restart that publishes
# the switch late raises nothing.
OFF_CYCLES = 3


@dataclass(frozen=True)
class RealTimeControlStep:
    off_cycles: int
    raise_issue: bool = False
    clear_issue: bool = False


def next_step(state: str | None, off_cycles: int) -> RealTimeControlStep:
    """The count of cycles read off so far and what to do about it.

    `on` clears the repair. `off` counts toward it. Anything else, such as a switch that is
    missing, unknown or unavailable, changes nothing: GivTCP not publishing is another repair's
    business, and an EMS has no such switch.
    """
    value = (state or "").lower()
    if value == "on":
        return RealTimeControlStep(0, clear_issue=True)
    if value == "off":
        count = off_cycles + 1
        return RealTimeControlStep(count, raise_issue=count >= OFF_CYCLES)
    return RealTimeControlStep(off_cycles)
