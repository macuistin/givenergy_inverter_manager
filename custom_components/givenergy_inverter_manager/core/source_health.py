"""source_health.py: what the entities a device is based on are doing, and whether that is a fault.

The EV charger and the hot water read other integrations' entities. Their state and when they
last reported go on this integration's own entities as attributes, so a stale or missing source
can be seen. Home Assistant sets `last_reported` on every write of a state, so a source that has
stopped reporting shows an old time even when its value has not changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..lib.timeutil import elapsed_seconds

# A hot water temperature can sit still for a long while, so the limit is an hour.
SENSOR_STALE_AFTER_S = 3600

OK = "ok"
ERROR = "error"


@dataclass(frozen=True)
class Source:
    """One entity another device is based on, as read this cycle.

    state is None when the entity does not exist. A switch reports only when it changes, so
    only a sensor can be called stale.
    """

    role: str
    entity_id: str
    state: str | None
    last_reported: datetime | None
    can_be_stale: bool = True


def age_s(source: Source, now: datetime) -> float | None:
    """Seconds since the source last reported, None without a report time."""
    if source.last_reported is None:
        return None
    return max(0.0, elapsed_seconds(source.last_reported, now))


def problem(source: Source, now: datetime) -> str | None:
    """What is wrong with the source, in words, or None when it is fine."""
    if source.state is None:
        return f"{source.role} ({source.entity_id}) does not exist"
    if source.state == "unavailable":
        return f"{source.role} ({source.entity_id}) is unavailable"
    age = age_s(source, now)
    if source.can_be_stale and age is not None and age > SENSOR_STALE_AFTER_S:
        return f"{source.role} ({source.entity_id}) has not reported for {int(age // 60)} minutes"
    return None


def describe(sources: tuple[Source, ...], now: datetime) -> list[dict[str, Any]]:
    """The sources as state attributes: entity, state, when it last reported and how long ago."""
    rows: list[dict[str, Any]] = []
    for source in sources:
        age = age_s(source, now)
        rows.append(
            {
                "role": source.role,
                "entity_id": source.entity_id,
                "state": source.state if source.state is not None else "missing",
                "last_reported": source.last_reported.isoformat() if source.last_reported else None,
                "age_minutes": None if age is None else round(age / 60, 1),
            }
        )
    return rows


def status(sources: tuple[Source, ...], now: datetime) -> tuple[str, str]:
    """ok with an empty cause, or error with every problem joined."""
    problems = [text for source in sources if (text := problem(source, now))]
    return (ERROR, "; ".join(problems)) if problems else (OK, "")
