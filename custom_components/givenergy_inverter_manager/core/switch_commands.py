"""When a switch the manager drives stops taking its commands, and when that clears.

The immersion heater is switched through a plug or relay that Home Assistant reaches by a cloud
or a radio. When that link fails, for example a cloud account that needs to sign in again, the
service call is rejected or the switch reads unavailable, and the heater never changes while the
plan says it should. One failure can be a blip, so a repair waits for a second one in a row. A
command that goes through clears it. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# Commands in a row that must fail before a repair appears. The actuator sends at most one
# automatic command every ten minutes, so this is about ten minutes of a heater that cannot be
# switched.
FAILURES_BEFORE_REPAIR = 2


@dataclass(frozen=True)
class CommandHealth:
    """The failures in a row so far, whether the repair is up, and the last reason."""

    failures: int = 0
    raised: bool = False
    reason: str = ""


@dataclass(frozen=True)
class CommandStep:
    health: CommandHealth
    raise_issue: bool = False
    clear_issue: bool = False


def after_failure(health: CommandHealth, reason: str) -> CommandStep:
    """Count one more failed command. From the second in a row the repair is asked for.

    The repair is asked for again on each later failure, so it carries the latest reason.
    """
    failures = health.failures + 1
    raised = failures >= FAILURES_BEFORE_REPAIR
    return CommandStep(CommandHealth(failures, raised, reason), raise_issue=raised)


def after_success(health: CommandHealth) -> CommandStep:
    """A command went through. Start the count again, and clear the repair if it was up."""
    return CommandStep(CommandHealth(), clear_issue=health.raised)
