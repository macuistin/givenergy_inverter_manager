---
description: "core/ stays free of Home Assistant, and how golden files are pinned and changed"
paths:
  - "custom_components/givenergy_inverter_manager/core/**"
  - "tests/core/**"
  - "tests/golden_*.json"
---

# core/ and golden files

## What core/ is

- `core/` holds decisions, tariff and accumulation maths, and the text of reports. It imports the
  standard library and the package's `const`, `discovery` and `logging` modules. It never imports
  `homeassistant`. `test_core_package_does_not_import_home_assistant` in `tests/test_metadata.py`
  fails the build if it does.
- Inputs are plain values and frozen dataclasses (`CycleInputs`, `RawSensorValues`, `TariffConfig`).
  Outputs are values or dataclasses (`CoordinatorData`, `ChargeDecision`). No `hass`, no files, no
  network.
- Pass the time in (`CycleInputs.now`, or a `now` argument). Do not read the wall clock in a new
  function. `tests/core/test_frozen_dates.py` uses 2031 dates so a stray `date.today()` fails.
- Anything Home Assistant specific goes in `coordinator.py` or a platform file, which calls `core/`.
  Keep value logic longer than one expression out of the description tables: put it in
  `sensor_values.py` (pure) and test it in `tests/test_sensor_values.py`.
- Decision text (`reason` strings) is output. Changing a reason changes the golden files below.

## Golden files

A golden file pins the output of a function over many inputs. It exists so a refactor cannot change
behaviour. It is not a place to record what the code happens to do.

| File | Pinned by | Holds |
| --- | --- | --- |
| `tests/core/golden_engine_snapshots.json` | `test_engine_snapshots.py` | Every `CoordinatorData` field that moves, over 255 engine cases |
| `tests/core/golden_reporting.json` | `test_reporting_golden.py` | Report HTML and state text, as hashes plus four readable cases |
| `tests/core/golden_rules_grid.json` | `test_rules_golden_grid.py` | Rule outputs over a seeded random grid, reasons included |
| `tests/core/golden_charge_targets.json` | `test_charge_target_pinned.py` | Charge decisions with no load history |
| `tests/golden_accumulation.json` | `test_accumulation_golden.py` | Midnight reset and storage round trip |
| `tests/golden_logging.json` | `test_logging_golden.py` | Log line wording |
| `tests/golden_services.json` | `test_services.py` | Service action responses |
| `tests/golden_dashboard_matrix.json` | `test_dashboard_matrix.py` | Digest of the dashboard per device combination |
| `tests/ha_e2e/golden/config_flow_forms.json` | `test_config_flow_forms_golden_e2e.py` | Every setup, reconfigure and options form |
| `tests/ha_e2e/entity_snapshot.json` | `test_entity_snapshot.py` | Entity ids, keys and names |

## Rules for a golden file

- A refactor never changes a golden file. If one fails after a refactor, the refactor changed
  behaviour. Fix the code.
- Change a golden file only when behaviour changes on purpose. Look at the diff before you commit it.
- List what moved. In the PR, name the leaves or rows that changed and say why each one should.
  For `golden_engine_snapshots.json`, also add a paragraph to the docstring of
  `tests/core/test_engine_snapshots.py` in the same style as the existing ones: how many cases moved,
  which leaves, and which test pins the new behaviour.
- Add a new test that pins the new behaviour in its own file. The golden update alone is not evidence.
- A new field on `CoordinatorData` adds a leaf to every case. State that no case moved otherwise.
- Do not edit a golden file by hand to make a test pass. Use `/regenerate-goldens`.
