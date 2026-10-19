"""outcome.py: one write and what the entity read back afterwards, as a log line."""

from __future__ import annotations

from dataclasses import dataclass

MISMATCH = "✗ MISMATCH — wrote but read back different value"
ACCEPTED = "✓ accepted"
OUTCOME_FORMAT = "  GIVTCP WRITE  step=%d  entity=%s  wrote=%r  read_back=%r  %s"


@dataclass(frozen=True)
class WriteOutcome:
    """One GivTCP write and what the entity read back afterwards."""

    step: int
    entity_id: str
    wrote: object
    read_back: object
    accepted: bool

    def log_args(self) -> tuple[object, ...]:
        """The values for OUTCOME_FORMAT."""
        status = ACCEPTED if self.accepted else MISMATCH
        return (self.step, self.entity_id, self.wrote, self.read_back, status)
