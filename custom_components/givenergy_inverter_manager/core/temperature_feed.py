"""When a hot water temperature sensor that reads nothing should raise a repair.

A cylinder thermometer is a small device reached over Wi-Fi or a radio. When it drops out, its
entity reads unavailable or unknown, and the water temperature, the ready-by plan and the
temperature controls go with it. A restart publishes the sensors a little late, so a repair waits
for the sensor to stay unreadable for a while. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping

# Cycles in a row a sensor must read nothing before a repair appears. A cycle is 30 seconds,
# so this is about five minutes.
SILENT_CYCLES = 10


def next_counts(counts: Mapping[str, int], readable: Mapping[str, bool]) -> dict[str, int]:
    """The cycles each sensor has read nothing in a row, after one more cycle.

    A sensor that is readable starts again from 0. A sensor that is no longer configured is
    dropped, so removing it clears its repair.
    """
    return {entity: 0 if ok else counts.get(entity, 0) + 1 for entity, ok in readable.items()}


def silent_sensors(counts: Mapping[str, int]) -> tuple[str, ...]:
    """The sensors that have read nothing for SILENT_CYCLES cycles in a row, in order."""
    return tuple(entity for entity, cycles in counts.items() if cycles >= SILENT_CYCLES)
