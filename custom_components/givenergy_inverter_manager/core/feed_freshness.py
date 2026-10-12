"""
feed_freshness.py: tell a frozen GivTCP feed from a quiet one.

When the GivTCP add-on stops, its MQTT entities keep their last retained values. They are not
`unavailable`, so the check for a silent feed never fires, and the integration plans from
readings that no longer move.

The signal is when an entity was last reported, never its value. Home Assistant sets
`last_reported` on every write of a state, even when the value is the same, so a steady reading
(SoC at 100%, solar at 0 W overnight) stays fresh while GivTCP publishes. The feed is frozen when
the newest report across the entities read each cycle is older than GIVTCP_FROZEN_AFTER_S.

Entities that are missing have no report and are left out. When none has one, there is nothing
to judge and the feed is not called frozen: the silent check owns that case.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ..const import GIVTCP_FROZEN_AFTER_S
from .timeutil import elapsed_seconds


def newest_report(reported: Iterable[datetime | None]) -> datetime | None:
    """The latest time any entity was reported, None when none has a time."""
    times = [at for at in reported if at is not None]
    return max(times) if times else None


def frozen_age_s(newest: datetime | None, now: datetime) -> float | None:
    """Seconds since the newest report when that is over the limit, else None."""
    if newest is None:
        return None
    age = elapsed_seconds(newest, now)
    return age if age > GIVTCP_FROZEN_AFTER_S else None
