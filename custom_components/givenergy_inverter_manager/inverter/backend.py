"""
backend.py: the jobs the coordinator needs from an inverter.

The coordinator talks to an InverterBackend. An adapter does the jobs for one inverter
integration and is the only code that knows that integration's entity names, its sign
conventions or the order its writes must go in. GivTCP is the only adapter today
(inverter/givtcp).

This module imports no Home Assistant code. Every method that needs an entity id takes the
effective config, because the ids are stored there and an options change can alter them.
Writes are the adapter's job to do and the coordinator's job to decide: the dry-run check and
the choice of what to write stay in the coordinator, so a backend only ever sees a write that
is going to happen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..core.inverter_values import (
    ChargePlan,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)


class ChargeSlot(Protocol):
    """A charge window on the inverter, other than the one the manager owns."""

    @property
    def number(self) -> int: ...

    @property
    def start(self) -> str: ...  # HH:MM

    @property
    def end(self) -> str: ...  # HH:MM

    @property
    def label(self) -> str: ...


@runtime_checkable
class InverterBackend(Protocol):
    """Reads one inverter and writes its charge settings."""

    @property
    def identity(self) -> InverterIdentity:
        """The serial, the entity-name prefix and the display name."""
        ...

    def read(self, cfg: Mapping[str, Any]) -> InverterValues:
        """One read of power, charge, counters and the age of the data, in our sign convention."""
        ...

    def feed_status(self, cfg: Mapping[str, Any], now: datetime) -> FeedStatus:
        """Whether the inverter integration is giving live numbers, and why not when it is not."""
        ...

    async def apply_charge_plan(self, cfg: Mapping[str, Any], plan: ChargePlan) -> WriteResult:
        """Enable the schedule, set the window and the target, then the enable-target switch.

        The skip-charge night sends the same plan with the minimum as the target.
        """
        ...

    async def apply_floor_target(self, cfg: Mapping[str, Any], soc: int) -> WriteResult:
        """Raise the target to a cheap-rate floor. A higher target already set is kept."""
        ...

    def other_active_charge_slots(self, cfg: Mapping[str, Any]) -> Sequence[ChargeSlot]:
        """Charge windows set by something else. Reads only."""
        ...

    async def clear_charge_slot(self, slot: ChargeSlot) -> bool:
        """Set one slot back to unused. False when a write was not taken."""
        ...

    def read_rate_defaults(self, cfg: Mapping[str, Any]) -> RateDefaults | None:
        """The rates the inverter integration holds, for the setup tariff page. None if none."""
        ...

    def watched_entity_ids(self, cfg: Mapping[str, Any]) -> tuple[str, ...]:
        """The entities the write audit watches for changes the manager did not make."""
        ...

    def solar_energy_entity_id(self, cfg: Mapping[str, Any]) -> str | None:
        """The entity that counts today's solar energy, used to seed the forecast history."""
        ...

    def rediscover(self, all_states: Mapping[str, Any]) -> None:
        """Look again for entities that can appear after setup, such as battery packs."""
        ...

    def listen_for_confirmations(self, listener: Any) -> None:
        """Tell the listener whether the inverter took each value written from now on."""
        ...

    def cooldown_active(self, entity_id: str, name: str, value: object) -> bool:
        """True when this value was written to the entity inside the write cooldown window."""
        ...

    def start_cooldown(self, entity_id: str, value: object) -> None:
        """Record that this value is being written to the entity now."""
        ...

    @property
    def write_count(self) -> int:
        """Register writes made so far over the life of the inverter."""
        ...

    @write_count.setter
    def write_count(self, count: int) -> None: ...


def describe_charge_slots(slots: Sequence[ChargeSlot]) -> str:
    """The slots as one readable line, for example 'Slot 2 (00:00 to 08:00)'."""
    return ", ".join(slot.label for slot in slots)
