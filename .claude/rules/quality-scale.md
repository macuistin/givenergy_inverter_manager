---
description: "The Integration Quality Scale file: what it claims, how to change it, how exemptions are judged"
paths:
  - "custom_components/givenergy_inverter_manager/quality_scale.yaml"
  - "custom_components/givenergy_inverter_manager/manifest.json"
  - "tests/test_quality_scale_rules.py"
---

# Quality scale

`quality_scale.yaml` is the record of which Home Assistant quality scale rules the integration
meets. Home Assistant does not grade custom integrations, so the file is the only evidence.

- Every rule of Bronze, Silver, Gold and Platinum is listed, as `done`, `todo` or `exempt`.
  `tests/test_quality_scale_rules.py` holds Home Assistant's rule lists and fails when the yaml
  lacks one. When Home Assistant adds a rule, add it to the test and the yaml together.
- Change a rule's status in the same pull request as the code, test or doc that earns it. A `done`
  comment names where the proof is.
- Challenge every `exempt` against the code before writing or keeping it. A reason must be true of
  the code today, and name what would end it (for example a published client library).
- The tier is claimed in `manifest.json` (`quality_scale`) and in `CLAUDE.md` only when every rule
  of that tier and the ones below is `done` or `exempt`. Never claim a tier early.
- A flow that asks for entities checks that they exist and are not unavailable before it creates
  or changes the entry (`unavailable_wiring`), in setup and in reconfigure.
- `config_flow.py`, `config_helpers.py` and `wizard/` stay at 100% line coverage in
  `tests/ha_e2e/`. A new page or step gets an end-to-end test. Mark an abstract method
  `# pragma: no cover` and delete a branch no input can reach.
- Silver: every module stays above 95% line coverage over both suites together, the rule's
  "all integration modules". `scripts/check_coverage.py` checks it and the `coverage` job in
  `tests.yml` runs it, so a new module or branch needs tests in the same change. Mark only a
  Protocol body or an abstract method as excluded.
- Gold devices: the EV charger and Immersion are their own devices, `via_device` the main one
  (`DeviceGroup` in `core/devices.py`, `device_info` in `entity.py`). A new entity takes its group
  from `requires`. It never moves an existing entity ID or unique ID, so `tests/ha_e2e/
  test_device_split_upgrade_e2e.py` seeds the old registry and checks the IDs survive. Names do
  not repeat the device name. `remove_stale_devices` and `async_remove_config_entry_device` let
  a device go once its hardware is gone, never the main device.
