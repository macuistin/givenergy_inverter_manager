"""
sequence.py: the order GivTCP needs its charge settings written in.

The sequence is the one batpred and givenergy-local both identify as necessary for GivEnergy
inverters. Every write goes through the GivTCPWriter, so each one is read first, held to the
cooldown, read back and counted.

Dry run is not checked here. The coordinator decides whether to write, and a backend only
ever sees a write that is going to happen.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import time
from typing import Any

from .defaults import GIVTCP_MAX_CHARGE_TARGET_PCT, GIVTCP_MIN_CHARGE_TARGET_PCT
from .discovery import UNUSED_SLOT_TIME, ActiveChargeSlot
from .keys import (
    KEY_CHARGE_END_TIME_ENTITY,
    KEY_CHARGE_START_TIME_ENTITY,
    KEY_ENABLE_CHARGE_SCHEDULE,
    KEY_ENABLE_CHARGE_TARGET,
    KEY_TARGET_SOC_ENTITY,
)
from .status import WriteStatus
from .values import ChargePlan, WriteResult
from .writer import (
    GivTCPWriter,
    SwitchState,
    VerifiedWrite,
    _number_write,
    _select_write,
    _switch_write,
    state_as_int,
)

_LOG = logging.getLogger(__name__)


def clamp_charge_target(target_soc: float) -> int:
    """Limit a charge target to the range GivTCP accepts."""
    return max(GIVTCP_MIN_CHARGE_TARGET_PCT, min(GIVTCP_MAX_CHARGE_TARGET_PCT, int(target_soc)))


def _clamp_and_report(target_soc: int) -> int:
    """Clamp a charge target to what GivTCP accepts, warning when it had to change."""
    clamped = clamp_charge_target(target_soc)
    if clamped != target_soc:
        _LOG.warning(
            "Charge target %s%% is outside the range GivTCP accepts (%d-%d%%), using %d%%",
            target_soc,
            GIVTCP_MIN_CHARGE_TARGET_PCT,
            GIVTCP_MAX_CHARGE_TARGET_PCT,
            clamped,
        )
    return clamped


_PlanWrite = tuple[str, VerifiedWrite | None]


def _plan_writes(cfg: Mapping[str, Any], plan: ChargePlan, target_soc: int) -> list[_PlanWrite]:
    """The five writes of a charge plan, in order. None where the entity is not configured."""
    schedule = cfg.get(KEY_ENABLE_CHARGE_SCHEDULE)
    start = cfg.get(KEY_CHARGE_START_TIME_ENTITY)
    end = cfg.get(KEY_CHARGE_END_TIME_ENTITY)
    target = cfg.get(KEY_TARGET_SOC_ENTITY)
    enable_target = cfg.get(KEY_ENABLE_CHARGE_TARGET)
    wanted = SwitchState.ON if plan.enable_charge_target else SwitchState.OFF
    return [
        (
            "enable charge schedule",
            schedule and _switch_write(schedule, SwitchState.ON, "enable charge schedule", 1),
        ),
        (
            "charge window start",
            start
            and _select_write(
                start, plan.window_start.strftime("%H:%M:%S"), "charge window start", 2
            ),
        ),
        (
            "charge window end",
            end
            and _select_write(end, plan.window_end.strftime("%H:%M:%S"), "charge window end", 3),
        ),
        ("charge target", target and _number_write(target, target_soc, "charge target", 4)),
        (
            "enable charge target",
            enable_target and _switch_write(enable_target, wanted, "enable charge target", 5),
        ),
    ]


async def _write_step(writer: GivTCPWriter, write: VerifiedWrite | None) -> WriteStatus:
    return WriteStatus.REFUSED if not write else await writer.write_verified(write)


async def apply_charge_plan(
    writer: GivTCPWriter, cfg: Mapping[str, Any], plan: ChargePlan
) -> WriteResult:
    """
    Apply a charge target and window to GivTCP in the correct order.

      1. Enable the charge schedule  (switch ..._enable_charge_schedule)
      2. Set the charge window start  (select ..._charge_start_time_slot_1)
      3. Set the charge window end    (select ..._charge_end_time_slot_1)
      4. Set the target SoC           (number ..._target_soc)
      5. Enable the charge target     (switch ..._enable_charge_target)

    Step 5 is critical: without the enable-charge-target switch on, the inverter silently
    ignores the target register entirely. The plan says whether it should be on (see
    ChargePlan.for_target). The switch is not turned on when writing the target failed,
    because the inverter would then limit charging to a stale target.
    """
    target_soc = _clamp_and_report(plan.target_soc)
    writes = _plan_writes(cfg, plan, target_soc)
    failed: list[str] = []
    for index, (name, write) in enumerate(writes):
        if index == 4 and plan.enable_charge_target and "charge target" in failed:
            _LOG.warning(
                "Charge target %d%% could not be written — not enabling the charge target",
                target_soc,
            )
            return WriteResult(tuple(failed))
        if not await _write_step(writer, write):
            failed.append(name)
    failed += _not_confirmed(writer, writes, set(failed))
    _LOG.info(
        "Charge target write-back complete: %d%% window %s–%s enable_target=%s%s",
        target_soc,
        plan.window_start.strftime("%H:%M:%S"),
        plan.window_end.strftime("%H:%M:%S"),
        plan.enable_charge_target,
        f", not confirmed: {', '.join(failed)}" if failed else "",
    )
    return WriteResult(tuple(failed))


def _not_confirmed(
    writer: GivTCPWriter, writes: list[_PlanWrite], already_failed: set[str]
) -> list[str]:
    """The settings that were sent but do not hold their value after the read-backs.

    The plan is not in force until each setting holds, so the caller needs to know, and to be
    able to send the same values again. The writer releases the cooldown of a write it could
    not confirm. A setting that confirmed late shows as held here and is not reported.
    """
    missed = []
    for name, write in writes:
        if name in already_failed or not write:
            continue
        if writer.is_unconfirmed(write):
            writer.release_cooldown(write)
            missed.append(f"{name} (not confirmed)")
    return missed


async def apply_charge_window(
    writer: GivTCPWriter, cfg: Mapping[str, Any], start: time, end: time
) -> WriteStatus:
    """Set slot 1 start, then end, and leave the target and the switches as they are."""
    return await writer.set_select(
        cfg.get(KEY_CHARGE_START_TIME_ENTITY),
        start.strftime("%H:%M:%S"),
        "charge window start",
        step=2,
    ) and await writer.set_select(
        cfg.get(KEY_CHARGE_END_TIME_ENTITY),
        end.strftime("%H:%M:%S"),
        "charge window end",
        step=3,
    )


async def apply_floor_target(
    writer: GivTCPWriter, cfg: Mapping[str, Any], soc: int, get_state
) -> WriteResult:
    """Write SoC target and enable charge target switch for cheap rate floor top-up.

    Uses the same read-before-write, cooldown, write counting and read-back
    helpers as the overnight charge target so the inverter registers are not
    written more often than necessary. The floor only raises the target. A
    higher target already on the inverter, such as the overnight charge
    target, is kept. The charge target is not enabled when the target could not be
    written.
    """
    target_entity = cfg.get(KEY_TARGET_SOC_ENTITY)
    current = state_as_int(get_state(target_entity)) if target_entity else None
    soc = clamp_charge_target(max(soc, current) if current is not None else soc)
    if not await writer.set_number(target_entity, soc, "floor top-up"):
        return WriteResult(("floor top-up",))
    if not await writer.set_switch(
        cfg.get(KEY_ENABLE_CHARGE_TARGET), SwitchState.ON, "floor top-up enable"
    ):
        return WriteResult(("floor top-up enable",))
    return WriteResult()


async def clear_charge_slot(writer: GivTCPWriter, slot: ActiveChargeSlot) -> WriteStatus:
    """Write 00:00:00 to the slot's start, then its end. Stops at the first failed write."""
    name = f"clear other slot {slot.number}"
    return await writer.set_select(
        slot.start_entity_id, UNUSED_SLOT_TIME, f"{name} start"
    ) and await writer.set_select(slot.end_entity_id, UNUSED_SLOT_TIME, f"{name} end")
