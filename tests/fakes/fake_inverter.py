"""A backend that implements only the InverterBackend interface.

It names no inverter integration and holds no Home Assistant objects, so a test of the
coordinator's choices can run against it. Every write is recorded in order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from custom_components.givenergy_inverter_manager.core.inverter_values import (
    ChargePlan,
    FeedState,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)


@dataclass(frozen=True)
class FakeSlot:
    number: int
    start: str
    end: str

    @property
    def label(self) -> str:
        return f"Slot {self.number} ({self.start} to {self.end})"


@dataclass
class FakeInverter:
    """Returns what the test sets and records what the coordinator writes."""

    values: InverterValues = field(default_factory=InverterValues)
    status: FeedStatus = field(default_factory=lambda: FeedStatus(FeedState.PUBLISHING))
    rate_defaults: RateDefaults | None = None
    slots: list[FakeSlot] = field(default_factory=list)
    watched: tuple[str, ...] = ()
    fail_steps: tuple[str, ...] = ()
    plans: list[ChargePlan] = field(default_factory=list)
    floor_targets: list[int] = field(default_factory=list)
    cleared: list[FakeSlot] = field(default_factory=list)

    @property
    def identity(self) -> InverterIdentity:
        return InverterIdentity(serial="FAKE0001", prefix="fake_", display_name="Fake inverter")

    def read(self, cfg: Mapping[str, Any]) -> InverterValues:
        return self.values

    def feed_status(self, cfg: Mapping[str, Any]) -> FeedStatus:
        return self.status

    async def apply_charge_plan(self, cfg: Mapping[str, Any], plan: ChargePlan) -> WriteResult:
        self.plans.append(plan)
        return WriteResult(self.fail_steps)

    async def apply_floor_target(self, cfg: Mapping[str, Any], soc: int) -> WriteResult:
        self.floor_targets.append(soc)
        return WriteResult(self.fail_steps)

    def other_active_charge_slots(self, cfg: Mapping[str, Any]) -> Sequence[FakeSlot]:
        return tuple(self.slots)

    async def clear_charge_slot(self, slot: FakeSlot) -> bool:
        self.cleared.append(slot)
        return not self.fail_steps

    def read_rate_defaults(self, cfg: Mapping[str, Any]) -> RateDefaults | None:
        return self.rate_defaults

    def watched_entity_ids(self, cfg: Mapping[str, Any]) -> tuple[str, ...]:
        return self.watched
