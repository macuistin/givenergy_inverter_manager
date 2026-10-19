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
from .discovery import UNUSED_SLOT_TIME
from .keys import (
    KEY_CHARGE_END_TIME_ENTITY,
    KEY_CHARGE_START_TIME_ENTITY,
    KEY_ENABLE_CHARGE_SCHEDULE,
    KEY_ENABLE_CHARGE_TARGET,
    KEY_TARGET_SOC_ENTITY,
)
from .values import ChargePlan, WriteResult
from .writer import (
    GivTCPWriter,
    SwitchState,
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
    failed: list[str] = []

    def step(name: str, ok: bool) -> bool:  # noqa: FBT001
        if not ok:
            failed.append(name)
        return ok

    step(
        "enable charge schedule",
        await writer.set_switch(
            cfg.get(KEY_ENABLE_CHARGE_SCHEDULE),
            SwitchState.ON,
            "enable charge schedule",
            step=1,
        ),
    )
    start_str = plan.window_start.strftime("%H:%M:%S")
    end_str = plan.window_end.strftime("%H:%M:%S")
    step(
        "charge window start",
        await writer.set_select(
            cfg.get(KEY_CHARGE_START_TIME_ENTITY), start_str, "charge window start", step=2
        ),
    )
    step(
        "charge window end",
        await writer.set_select(
            cfg.get(KEY_CHARGE_END_TIME_ENTITY), end_str, "charge window end", step=3
        ),
    )
    target_written = step(
        "charge target",
        await writer.set_number(
            cfg.get(KEY_TARGET_SOC_ENTITY), target_soc, "charge target", step=4
        ),
    )
    if plan.enable_charge_target and not target_written:
        _LOG.warning(
            "Charge target %d%% could not be written — not enabling the charge target",
            target_soc,
        )
        return WriteResult(tuple(failed))
    step(
        "enable charge target",
        await writer.set_switch(
            cfg.get(KEY_ENABLE_CHARGE_TARGET),
            SwitchState.ON if plan.enable_charge_target else SwitchState.OFF,
            "enable charge target",
            step=5,
        ),
    )
    failed += _not_confirmed(writer, cfg, plan, set(failed))
    _LOG.info(
        "Charge target write-back complete: %d%% window %s–%s enable_target=%s%s",
        target_soc,
        start_str,
        end_str,
        plan.enable_charge_target,
        f", not confirmed: {', '.join(failed)}" if failed else "",
    )
    return WriteResult(tuple(failed))


def _not_confirmed(
    writer: GivTCPWriter,
    cfg: Mapping[str, Any],
    plan: ChargePlan,
    already_failed: set[str],
) -> list[str]:
    """The settings that were sent but do not hold their value after the read-backs.

    The writer counts a sent write as success even when every read-back showed the old value,
    because GivTCP can be slow to publish. The plan is not in force until each setting holds, so
    the caller needs to know, and to be able to send the same values again. The cooldown that
    stops the same value being sent twice within five minutes is released for each one.
    """
    wanted = (
        (
            "enable charge schedule",
            _switch_write(
                cfg.get(KEY_ENABLE_CHARGE_SCHEDULE), SwitchState.ON, "enable charge schedule", 1
            ),
        ),
        (
            "charge window start",
            _select_write(
                cfg.get(KEY_CHARGE_START_TIME_ENTITY),
                plan.window_start.strftime("%H:%M:%S"),
                "charge window start",
                2,
            ),
        ),
        (
            "charge window end",
            _select_write(
                cfg.get(KEY_CHARGE_END_TIME_ENTITY),
                plan.window_end.strftime("%H:%M:%S"),
                "charge window end",
                3,
            ),
        ),
        (
            "charge target",
            _number_write(
                cfg.get(KEY_TARGET_SOC_ENTITY),
                clamp_charge_target(plan.target_soc),
                "charge target",
                4,
            ),
        ),
        (
            "enable charge target",
            _switch_write(
                cfg.get(KEY_ENABLE_CHARGE_TARGET),
                SwitchState.ON if plan.enable_charge_target else SwitchState.OFF,
                "enable charge target",
                5,
            ),
        ),
    )
    missed = []
    for name, write in wanted:
        if name in already_failed or not write.payload["entity_id"]:
            continue
        if writer.is_unconfirmed(write):
            writer.release_cooldown(write)
            missed.append(f"{name} (not confirmed)")
    return missed


async def apply_charge_window(
    writer: GivTCPWriter, cfg: Mapping[str, Any], start: time, end: time
) -> bool:
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


async def clear_charge_slot(writer: GivTCPWriter, slot) -> bool:
    """Write 00:00:00 to the slot's start, then its end. Stops at the first failed write."""
    name = f"clear other slot {slot.number}"
    return await writer.set_select(
        slot.start_entity_id, UNUSED_SLOT_TIME, f"{name} start"
    ) and await writer.set_select(slot.end_entity_id, UNUSED_SLOT_TIME, f"{name} end")
