---
description: "Hardware writes respect dry run, no forced export, optional devices may be absent or added later"
paths:
  - "custom_components/**"
  - "tests/**"
---

# Safety

The integration writes to real hardware: the inverter through GivTCP, the immersion switch and the
EV charger. A mistake costs money or leaves a battery at the wrong target.

## Dry run

- Every write to the inverter, the immersion switch and the EV charger checks `coordinator.is_dry_run`
  first. In dry run it records `Would ...` through `_record_skipped` (the **Last Skipped Action**
  sensor), logs a `DRY RUN:` line and sends nothing.
- This holds for the charge target and window, the skip-charge minimum, the cheap rate floor
  top-up, the EV mode change, the charge slot clear and the immersion actuator
  (`immersion_actuator.py` takes `is_dry_run` as a port). A new write path does the same.
- Decisions and sensors keep updating in dry run. Only the send is held back. Give a new write a
  test that sets `dry_run` and asserts nothing was sent (see `tests/test_dry_run_engine.py` and
  `tests/test_coordinator.py`).
- A `.givenergy_test_instance` file in the config folder forces dry run on (`TEST_INSTANCE_MARKER`).
  The coordinator reads it once at setup and `_effective_cfg` applies it, so every reader of
  `dry_run` agrees. Never read `CONF_DRY_RUN` straight from the entry in new code.
- Only the adapter writes to the inverter. The coordinator decides what to write, checks dry run,
  and calls the backend (`apply_charge_plan`, `apply_floor_target`, `clear_charge_slot`). The
  adapter's writes go through `inverter/givtcp/writer.py`, which reads before writing, applies a
  cooldown (`GIVTCP_MIN_WRITE_INTERVAL_S`) and reads back. Do not call a GivTCP service from
  anywhere else.
- A write that the inverter does not take (every read-back shows the old value) raises the repair
  `write_not_confirmed`. It is never raised in dry run. The decision lives in
  `core/write_confirmation.py`.
- The nightly charge write is retried at +2, +5, +10 and +20 minutes after the trigger when it
  fails, and not when less than 15 minutes of the window would remain (`core/charge_retry.py`).
  A write has failed when the feed is not live or a sent setting does not hold its value. Each
  retry goes through the same writer, so it is read back, counted and held to the cooldown, which
  a setting that did not take releases. Retries and a start-up catch-up call the backend through
  the coordinator's dry-run check, so dry run sends nothing. Notes about retries use the write
  log reason `retry`, and they are not writes. Re-planning inside the cheap window
  (`core/replan.py`, on only while the `charge_replan` switch is on) follows the same rules: it
  writes at most three times a night, never outside the window and never with a manual override,
  through the same checked writer. Its notes use the reason `replan`.
- Planning and writes stop while the feed is not live. That is a frozen feed (nothing reported for
  ten minutes, repair `givtcp_feed_frozen`), a paused GivTCP, or old data per GivTCP's `Data_Age`
  (repair `givtcp_not_answering`, feed state `stale`), judged by `feed_status` in
  `inverter/givtcp/reader.py`. A new write path checks them and tests that nothing is sent.

## What the integration never does

- No forced export to the grid: no export schedule or rate is written. Holding the battery back
  for the house (a pause or reserve, S22 and N21) is allowed once designed, as a verified write
  that never runs in dry run or on a frozen feed and is undone afterwards.
- It never stops or pauses an EV charger on a guess about whose car it is or why it is plugged in.
  For a Zappi with a charge mode entity it selects Eco+ and never Stopped or Fast. For a GivEnergy
  charger it selects Solar and never Grid or Hybrid, never writes Charge Control or Plug and Go.
  `pick_surplus_mode` skips any option with a forbidden word. No feature infers intent from load,
  presence or whose car it looks like.
- One exception: stopping charging outside a window taken from the published tariff, the same for
  any car (the EV window item in `ROADMAP.md`). That is a timing rule, not a judgement about a car.
  It must be opt-in and follow the tariff's own windows, not a time typed in separately.
- The write audit (`write_audit.py`) only records. It never reverts a change and never raises a repair.
  The Charge Target Conflict sensor and its banner read the log (`core/controller_conflict.py`) and
  nothing else. A second controller shows there, never as a repair. A system that changed kind
  (repair `system_looks_different`) is reported and never followed: the stored inverter stays the
  one managed until the user changes it.

## Optional devices

- The EV charger, the immersion switch and the immersion temperature sensor may be absent, and may
  be added or removed later. A feature that touches one has two paths, and both are tested:
  - absent: no entity, dashboard card, repair, error log or zero-valued sensor for it
  - added later: found on the next refresh or options change, with no reinstall and no manual step
- A sensor that needs a device sets `requires=Device.<X>` on its description
  (`core/devices.py`, `optional_devices.py`). A dashboard card needs a visibility condition
  (`.claude/rules/dashboard.md`).
- End-to-end tests for this start with the device missing: `tests/ha_e2e/test_optional_*_e2e.py`.
- Read data in code instead of asking the user to build a helper or template.
