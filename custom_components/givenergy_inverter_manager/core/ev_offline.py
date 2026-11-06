"""ev_offline.py: when to raise a repair for an EV charger that is not responding.

The charger state reads offline when its status sensor is unavailable or has stopped reporting
(lib/ev/state.py). A short drop, such as a cloud account refreshing, is not worth a repair, so
the state must hold for EV_OFFLINE_REPAIR_CYCLES updates in a row.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ten updates, about five minutes.
EV_OFFLINE_REPAIR_CYCLES = 10


@dataclass(frozen=True)
class OfflineStep:
    """Updates in a row the charger has been offline, and what to do with the repair."""

    cycles: int
    raise_issue: bool
    clear_issue: bool


def next_step(*, offline: bool, cycles: int) -> OfflineStep:
    """Count the update, raise the repair on the update the limit is reached, clear on recovery."""
    if not offline:
        return OfflineStep(0, False, cycles >= EV_OFFLINE_REPAIR_CYCLES)
    count = cycles + 1
    return OfflineStep(count, count == EV_OFFLINE_REPAIR_CYCLES, False)
