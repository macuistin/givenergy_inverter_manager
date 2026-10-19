"""_entity.py: what the client needs from an entity state, and the small reads on top of it.

A host hands the client a `get_state` callable. The object it returns needs a `state` and an
`attributes` mapping. `last_reported` is needed only to judge a frozen feed
(`GivTCPReader.feed_status`), and a state without it is treated as having no report time.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

_IGNORED = re.compile(r"[\s_\-]+")
_UNAVAILABLE = frozenset({"unavailable", "unknown", "none", ""})


class EntityState(Protocol):
    """One entity's state, as Home Assistant's `State` has it."""

    @property
    def state(self) -> str: ...

    @property
    def attributes(self) -> Mapping[str, Any]: ...


GetState = Callable[[str], EntityState | None]


def squash(text: str) -> str:
    """Lower case with spaces, underscores and hyphens removed, to compare option spellings."""
    return _IGNORED.sub("", text).casefold()


def usable(state: EntityState | None) -> str | None:
    """The state text, None when the entity is missing, unavailable or unknown."""
    text = None if state is None else str(state.state).strip()
    return None if text is None or text.casefold() in _UNAVAILABLE else text


def listed_options(state: EntityState | None) -> list[str] | None:
    """The options a select lists, None when it lists none."""
    listed = (getattr(state, "attributes", None) or {}).get("options")
    return [str(o) for o in listed] if listed else None


def attribute_limit(state: EntityState | None, name: str) -> float | None:
    """A numeric attribute such as `min` or `max`, None when absent or not a number."""
    value = (getattr(state, "attributes", None) or {}).get(name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def clamp_to_entity(
    value: float, state: EntityState | None, floor: float = 0, ceiling: float | None = None
) -> int:
    """Round *value* into the range the entity publishes, inside *floor* and *ceiling*.

    The entity's `min` and `max` narrow the range and never widen it. A limit that is not a
    number is ignored, and a `max` of 0 is a limit like any other. With no ceiling and no `max`
    the value is not capped.
    """
    low, high = floor, ceiling
    entity_min = attribute_limit(state, "min")
    entity_max = attribute_limit(state, "max")
    if entity_min is not None:
        low = max(low, entity_min)
    if entity_max is not None:
        high = entity_max if high is None else min(high, entity_max)
    value = max(value, low)
    return round(value if high is None else min(value, high))


def read_int(get_state: GetState, entity: str | None) -> int | None:
    """An entity's state as a whole number, None when it is missing or not numeric."""
    text = usable(get_state(entity)) if entity else None
    try:
        return int(float(text)) if text is not None else None
    except ValueError:
        return None
