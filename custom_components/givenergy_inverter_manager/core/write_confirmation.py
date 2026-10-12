"""
write_confirmation.py: which inverter settings did not take the value written.

The writer reads each setting back after it writes it. When every attempt reads back the old
value, the setting did not take. The cause is outside this integration (GivTCP's Real Time
Control is off, or GivTCP has stopped publishing) and it does not fix itself, so the user is told.

unconfirmed_step() and confirmed_step() keep the list of settings that did not take, and say what
to do with the repair:

  * RAISE when the list gained a setting or a setting's value changed, so the repair text is
    refreshed. A setting that fails again with the same value does nothing, so the repair is
    raised once per setting and never flaps.
  * CLEAR when the last setting on the list was confirmed.
  * NONE when nothing changed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .ev_base_rate import AlertAction


@dataclass(frozen=True)
class UnconfirmedWrite:
    """One setting the inverter did not take: its entity, what it is for, the value written."""

    entity_id: str
    name: str
    value: str


@dataclass(frozen=True)
class Unconfirmed:
    """The settings that did not take, in the order they failed."""

    writes: tuple[UnconfirmedWrite, ...] = ()


@dataclass(frozen=True)
class ConfirmationStep:
    """The list to keep and the action to take on the repair."""

    state: Unconfirmed
    action: AlertAction


def unconfirmed_step(state: Unconfirmed, write: UnconfirmedWrite) -> ConfirmationStep:
    """A write was read back as the old value after every attempt."""
    if write in state.writes:
        return ConfirmationStep(state, AlertAction.NONE)
    kept = tuple(w for w in state.writes if w.entity_id != write.entity_id)
    return ConfirmationStep(Unconfirmed((*kept, write)), AlertAction.RAISE)


def confirmed_step(state: Unconfirmed, entity_id: str) -> ConfirmationStep:
    """The entity holds the value asked for, after a write or on a later look."""
    remaining = tuple(w for w in state.writes if w.entity_id != entity_id)
    if len(remaining) == len(state.writes):
        return ConfirmationStep(state, AlertAction.NONE)
    action = AlertAction.RAISE if remaining else AlertAction.CLEAR
    return ConfirmationStep(Unconfirmed(remaining), action)


def describe_unconfirmed(writes: Sequence[UnconfirmedWrite]) -> str:
    """The settings for the repair text, for example `charge target (number.x, wrote 75)`."""
    return "; ".join(f"{w.name} ({w.entity_id}, wrote {w.value})" for w in writes)
