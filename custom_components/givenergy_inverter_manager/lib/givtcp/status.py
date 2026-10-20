"""status.py: what happened to one write, so a caller can tell a sent value from a skipped one."""

from __future__ import annotations

from enum import Enum


class WriteStatus(Enum):
    """The outcome of one write to the inverter.

    The value is truthy when nothing is known to have gone wrong: the entity already held it,
    it was sent and read back, it was sent but never read back, or the same value was sent
    inside the cooldown. It is falsy when nothing was sent because the write was refused, or
    when the call failed. Test `status is WriteStatus.WRITTEN` when the caller needs to know
    that the inverter holds the value.
    """

    ALREADY_SET = "already_set"
    """The entity held the value, so nothing was sent."""
    WRITTEN = "written"
    """Sent, and the read-back showed the value."""
    UNCONFIRMED = "unconfirmed"
    """Sent, but every read-back showed something else. A short cooldown holds the value."""
    COOLDOWN = "cooldown"
    """The same value was sent to this entity inside the cooldown, so nothing was sent."""
    REFUSED = "refused"
    """Nothing was sent: the entity is missing, unavailable or unknown, or cannot take it."""
    FAILED = "failed"
    """The service call raised, or the entity vanished after it."""

    def __bool__(self) -> bool:
        return self not in (WriteStatus.REFUSED, WriteStatus.FAILED)

    @property
    def confirmed(self) -> bool:
        """True when the inverter is known to hold the value."""
        return self in (WriteStatus.ALREADY_SET, WriteStatus.WRITTEN)

    @property
    def sent(self) -> bool:
        """True when a service call went to the inverter for this write."""
        return self in (WriteStatus.WRITTEN, WriteStatus.UNCONFIRMED)
