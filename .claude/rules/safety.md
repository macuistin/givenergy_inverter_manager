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
- Writes to GivTCP go through `givtcp_writer.py`, which reads before writing, applies a cooldown
  (`GIVTCP_MIN_WRITE_INTERVAL_S`) and reads back. Do not call a GivTCP service from anywhere else.

## What the integration never does

- No forced export or discharge. It writes no export or discharge schedule, rate or reserve to the
  inverter. The `pre_boost_export_*` sensors were retired for this reason. Do not propose features
  that rely on exporting from the battery.
- It never stops or pauses an EV charger. For a Zappi with a charge mode entity it selects Eco+ and
  never Stopped or Fast.
- The write audit (`write_audit.py`) only records. It never reverts a change and never raises a repair.

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
