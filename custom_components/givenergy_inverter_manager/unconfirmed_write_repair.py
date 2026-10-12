"""
unconfirmed_write_repair.py: raise and clear the repair for settings the inverter did not take.

The writer tells this listener when a write read back as the requested value and when every
attempt read back the old one. core/write_confirmation.py decides what to do with the repair.
A setting that no longer shows the old value is also noticed on the next cycle (recheck), for
GivTCP publishing the new state later than the retries waited.

Dry run sends nothing, so nothing can fail to be confirmed and nothing is raised.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from .core.ev_base_rate import AlertAction
from .core.write_confirmation import (
    ConfirmationStep,
    Unconfirmed,
    UnconfirmedWrite,
    confirmed_step,
    describe_unconfirmed,
    unconfirmed_step,
)
from .givtcp_writer import VerifiedWrite
from .logging import get_logger
from .repairs import async_create_write_not_confirmed_issue, async_delete_write_not_confirmed_issue

_LOG = get_logger(__name__)

# What a state object reads when the entity has no usable value.
_NO_VALUE = ("unavailable", "unknown")


class UnconfirmedWriteRepair:
    """Keeps the repair in step with the settings the inverter did not take."""

    def __init__(
        self,
        hass: HomeAssistant,
        is_dry_run: Callable[[], bool],
        get_state: Callable[[str], Any],
    ) -> None:
        self._hass = hass
        self._is_dry_run = is_dry_run
        self._get_state = get_state
        self._state = Unconfirmed()
        # How to tell that each listed entity now holds the value, by entity id.
        self._writes: dict[str, VerifiedWrite] = {}

    def not_confirmed(self, write: VerifiedWrite) -> None:
        """Every attempt read the old value back. Raise the repair, once per setting."""
        if self._is_dry_run():
            return
        item = UnconfirmedWrite(write.entity_id, write.name, str(write.shown))
        step = unconfirmed_step(self._state, item)
        if step.action is AlertAction.RAISE:
            self._writes[write.entity_id] = write
        self._apply(step)

    def confirmed(self, write: VerifiedWrite) -> None:
        """The entity holds the value. Take it off the repair."""
        self._apply(confirmed_step(self._state, write.entity_id))
        self._writes.pop(write.entity_id, None)

    def recheck(self) -> None:
        """Take off each setting that now holds its value, however it got there."""
        for entity_id, write in list(self._writes.items()):
            state = self._get_state(entity_id)
            if state is not None and state.state not in _NO_VALUE and write.matches(state):
                _LOG.info("%s now holds %s, so it is off the repair", entity_id, write.shown)
                self.confirmed(write)

    def clear(self) -> None:
        """Delete the repair and forget the list, as the integration unloads."""
        self._state = Unconfirmed()
        self._writes.clear()
        async_delete_write_not_confirmed_issue(self._hass)

    def _apply(self, step: ConfirmationStep) -> None:
        self._state = step.state
        if step.action is AlertAction.RAISE:
            async_create_write_not_confirmed_issue(
                self._hass, describe_unconfirmed(step.state.writes)
            )
        elif step.action is AlertAction.CLEAR:
            async_delete_write_not_confirmed_issue(self._hass)
