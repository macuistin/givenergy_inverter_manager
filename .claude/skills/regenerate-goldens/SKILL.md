---
name: regenerate-goldens
description: "Update the golden files after a deliberate behaviour change in GivEnergy Inverter Manager, and record what moved. Use when a golden test fails and the behaviour change is intended."
---

# Regenerate golden files

First decide whether the change is intended. A golden failure after a refactor is a bug in the
refactor, not a reason to regenerate. Only regenerate when behaviour is meant to change, and pin the
new behaviour with its own test. Rules: `.claude/rules/core-purity.md`.

A refactor moves no golden file. The one exception is a field the refactor removes or renames,
and then only that field moves: show in the PR that no other value changed.

Run from the repo root in the unit venv unless stated. Commit the golden change in its own commit
with the code that caused it, never alone.

## Files with a built-in switch

| File | Command |
| --- | --- |
| `tests/golden_dashboard_matrix.json` | `UPDATE_DASHBOARD_MATRIX=1 python -m pytest tests/test_dashboard_matrix.py` |
| `tests/golden_logging.json` | `UPDATE_LOGGING_GOLDEN=1 python -m pytest tests/test_logging_golden.py` |
| `docs/sensors.md` | `python scripts/gen_sensor_docs.py` |
| `tests/ha_e2e/golden/config_flow_forms.json` | Delete the file, run `python -m pytest tests/ha_e2e/test_config_flow_forms_golden_e2e.py -q` in the end-to-end venv. The test writes the file and fails. Run it again to pass |

After a dashboard change, list which sections moved with a test that names them. The matrix holds
one hash per scenario, so the file diff shows nothing readable. Regenerate it, then run it a second
time without the variable to confirm it passes.

## Files with no switch

These have no generator in the repo. Write a throwaway script outside the repo (the session
scratchpad), run it, and check `git diff`. Keep the file's JSON style, shown in brackets.

- `tests/core/golden_engine_snapshots.json` (compact JSON, `separators=(",", ":")`). Rebuild
  `fresh` and each case's `out` and `ev`, keeping `in`:

  ```python
  import json, sys
  from pathlib import Path
  sys.path.insert(0, ".")
  import tests.conftest  # installs the Home Assistant stubs
  from tests.core import engine_snapshot as snap
  from tests.core.flat_engine import build_coordinator_data
  from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData

  p = Path("tests/core/golden_engine_snapshots.json")
  g = json.loads(p.read_text())
  g["fresh"] = snap.snapshot(CoordinatorData())
  for case in g["cases"]:
      data, ev = build_coordinator_data(**{n: snap.decode(v) for n, v in case["in"].items()})
      case["out"], case["ev"] = snap.diff(snap.snapshot(data), g["fresh"]), ev
  p.write_text(json.dumps(g, separators=(",", ":")))
  ```

- `tests/core/golden_reporting.json` (`indent=1`). Regenerate after the engine file. Set
  `digests[i] = digest(render_all(cases[i]))`, each `readable[key] = render_all(cases[n])` where
  `key` is `<label>:<n>`, and each `handmade[i]["digest"] = digest(render_handmade(spec))`. The
  helpers are in `tests/core/reporting_snapshot.py`.
- `tests/core/golden_rules_grid.json`, `tests/core/golden_charge_targets.json` and
  `tests/golden_accumulation.json` (compact JSON). Re-run the function over each stored input and
  replace only the outputs that should move. Assert the moved rows are the ones you expect.
- `tests/golden_services.json` (`indent=2`). Replace the entries the failing test names.
- `tests/ha_e2e/entity_snapshot.json` (`indent=1`, rows sorted by `entity_id`). Add rows for new
  entities. Never edit an existing `entity_id` or `key`. That is a breaking change for users.

## Record what moved

1. Diff the old and new golden files and list the cases, rows or leaves that changed.
2. Check every change has a reason in the code change. An unexplained move is a bug.
3. For `golden_engine_snapshots.json`, add a paragraph to the docstring of
   `tests/core/test_engine_snapshots.py` in the existing style: how many of the 255 cases moved,
   which leaves, and which test pins the new behaviour.
4. Put the same list under Testing in the PR, and say if users see a change (Impact).
5. Run the unit suite, then the end-to-end suite, with no golden environment variables set.
