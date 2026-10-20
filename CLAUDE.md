# GivEnergy Inverter Manager

Rules for AI assistants working in this repo. `AGENTS.md` is a symlink to this file. The detailed
rules are in `.claude/rules/`, the repeatable jobs in `.claude/skills/`. Keep this file under 150
lines (a test enforces it) and put detail in a rule file, not here.

## What this is

A Home Assistant custom integration, distributed through HACS. It reads and writes a GivEnergy
inverter through an inverter backend, and GivTCP is the only backend today. It plans the overnight
charge, diverts solar surplus to an immersion heater and an EV charger, and tracks cost across
tariff periods. It targets the Silver tier of the Home Assistant quality scale.
`custom_components/givenergy_inverter_manager/quality_scale.yaml` lists which rules are done,
exempt or todo. Do not claim a tier the file does not support.

## Layout

The integration is `custom_components/givenergy_inverter_manager/`. Paths in this table are
inside it.

| Path | Role |
| --- | --- |
| `core/` | Pure Python decisions, tariff, accumulation maths and report text. No `homeassistant` imports |
| `const.py`, `conf.py`, `defaults.py`, `tuning.py` | `conf.py` holds the `CONF_` option keys, `defaults.py` the `DEFAULT_` values and `tuning.py` the numeric thresholds. None of the three imports anything. `const.py` re-exports all of them, so import from `const` |
| `lib/` | Packages written to be lifted out into their own repositories, one folder each. They import only the standard library and the `lib/` packages their `ALLOWED` row names. `lib/README.md` has the rules. `timeutil`, `ev` (EV charger model, discovery, sessions, base-rate alert) `tariff` (tariff model, cost accumulation, bill maths) and `heating` (hot-water ready-by planner) are in so far. `core/tariff.py` keeps the code that reads option keys |
| `coordinator.py` | Home Assistant bridge: asks the inverter backend for readings, calls `core/`, decides what to write and sends it through the backend, runs timers |
| `inverter/` | `backend.py` is the `InverterBackend` interface. It has no Home Assistant import |
| `inverter/givtcp/` | The GivTCP adapter: discovery, the verified writer and the write constants. The code that knows GivTCP entity names and write order |
| `core/inverter_values.py` | The frozen values the coordinator and a backend exchange (`InverterValues`, `ChargePlan`, `RateDefaults`, `WriteResult`, `FeedStatus`) |
| `core/system_types.py`, `core/system_text.py`, `core/entity_refs.py` | System kind and which inverter to manage, the setup text about it, and finding a wired entity again after its id changes. Devices are told apart by entity suffix, never by serial prefix alone |
| `config_flow.py`, `wizard/`, `core/wizard_*.py` | Setup wizard, options wizard and reconfigure (the inverter connection). `config_flow.py` only registers them. `config_helpers.py` merges entry data and options |
| `sensor.py`, `sensor_descriptions/` | One entity class and the description table, split by theme |
| `optional_devices.py`, `core/devices.py`, `discovery/` | The EV charger (`lib/ev/discover.py`: Zappi, GivEnergy charger and others), immersion switch and immersion sensor may be absent or added later. `discovery/forecast.py` finds the forecast |
| `controls.py` | The eight tuning controls: three switches and five numbers, each owning one option key |
| `dashboard/`, `strategy.py` | The dashboard builder, and the Lovelace strategy that serves it |
| `repairs.py`, `repair_flows.py`, `services.py` | Repair issues and their fix flows, service actions. `stored_dashboard_repair.py` checks the dashboard `update_dashboard` keeps current. `active_repairs.py` reads the open ones for the Active Repairs sensor |

## Architecture rules

- `core/` imports nothing from `homeassistant`, and nothing from `inverter/` at run time.
  `tests/test_metadata.py` enforces both.
- `lib/` imports nothing from `const.py`, `logging.py`, `core/`, `discovery/`, `inverter/` or
  `homeassistant`, not even under `TYPE_CHECKING`. Runtime packages live inside the integration folder
  because HACS ships only that folder. `tests/test_metadata.py` enforces both.
- Only `inverter/givtcp/` calls GivTCP services and knows its entity names and write order. The
  coordinator reads and writes through the `InverterBackend` interface. Known leaks, which a new
  change does not add to: `_check_system` in `coordinator.py` reads GivTCP's version sensor and
  calls `discover_givtcp_inverters`, and the wizard, `repairs.py`, `write_audit.py`,
  `unconfirmed_write_repair.py` and `dashboard/views.py` import from `inverter/givtcp/`.
- `entry.runtime_data` holds the coordinator (`GivEnergyConfigEntry`). Never use `hass.data[DOMAIN]`.
- `GivEnergyCoordinator` passes `config_entry=entry` to `DataUpdateCoordinator`.
- `async_reload_entry` calls `hass.config_entries.async_reload(entry.entry_id)`. It does not call
  `async_unload_entry` then `async_setup_entry` by hand.
- Which options saves reload is decided in `core/reload_policy.py` (`change_effect`). A new option
  key reloads until it is placed in `LIVE_KEYS`, and `tests/core/test_reload_policy.py` fails until it
  has a row.
- `.github/workflows/release.yml` publishes the GitHub release. The maintainer runs it from
  Actions > Release > Run workflow with a version, or pushes a `vX.Y.Z` tag. It tags the commit,
  uses the changelog section as notes, and marks an `a`, `b` or `rc` version a pre-release. A final
  release runs from `main`. Never run it, push a tag or create a release yourself.
  `scripts/set_version.py` sets and checks the version and prints the notes.

## Commands

Two virtualenvs, because the end-to-end plugin pins `homeassistant`, `pytest` and `pytest-asyncio`.
`docs/testing.md` has the setup. The code uses Python 3.14 syntax and the system Python may be
older, so make each venv with `uv venv --python 3.14 .venv`. Run all three before pushing.

```bash
ruff check custom_components tests scripts tools        # CI lints custom_components and tests
python -m pytest tests -q                               # unit suite, skips tests/ha_e2e
python -m pytest tests/ha_e2e -q                        # real Home Assistant, own venv
python scripts/gen_sensor_docs.py                       # rewrite docs/sensors.md after a sensor change
```

The end-to-end venv needs `requirements-test-e2e.txt` and Python 3.14.2 or newer. Run both suites
from the repo root. Use `ROOT` and `PKG` from `tests/helpers.py` for paths, never the working
directory. Test counts drift, so measure before quoting one.

## Inverter sign conventions

GivTCP publishes grid and battery power with the opposite sign to the one used inside this
integration. The GivTCP adapter negates both on read (`GivTCPReader.read` in
`inverter/givtcp/reader.py`). `_collect_raw` in `coordinator.py` only merges the result.

| Quantity | GivTCP entity | Inside the integration |
| --- | --- | --- |
| Grid power | positive is export | `grid_power_w` positive is import |
| Battery power | positive is discharging | `battery_power_w` positive is charging |
| Solar power | always positive | unchanged |

- Tests: `test_reads_grid_power_negative_when_exporting` and `test_reads_battery_power_discharging`
  in `tests/test_coordinator.py`. `tools/mock_givtcp.py` publishes in GivTCP's own convention.
- The **Battery Power** entity of this integration is positive when charging. The power flow card
  node reads it with `invert_state: true` (`dashboard/views.py`). A card that reads GivTCP's raw
  entity needs the opposite handling.
- Without the grid negation, exports would count as imports and inflate import cost.
- `house_load_w` is GivTCP's load reading. It covers the inverter side only, not loads wired
  straight to the consumer unit. Those show as grid import while solar runs. That is a GivTCP and
  wiring limit, not a bug here.
- GivTCP daily energy counters replace the integrated kWh for today when present
  (`_apply_daily_counters` in `core/engine.py`). `core/counter_guard.py` screens them first and
  drops a rise the inverter could not have delivered, such as a counter that jumped units.

## Rules by topic

Read the file that matches the code you are changing.

| File | Covers |
| --- | --- |
| `.claude/rules/home-assistant.md` | Entities, state limits, config and options flows, reloads, repairs, services |
| `.claude/rules/core-purity.md` | `core/` limits, golden files, how and when to change them |
| `.claude/rules/tests.md` | Test layout, what each suite proves, rules for new and changed tests |
| `.claude/rules/safety.md` | Dry run, no forced export, optional devices |
| `.claude/rules/dashboard.md` | The stored dashboard and the strategy, who sees Settings, HACS cards and the golden file |
| `.claude/rules/dashboard-changes.md` | Adding or moving a card, chart or section: layout, apexcharts limits, the steps |
| `.claude/rules/python-style.md` | Clean Code limits that ruff enforces |
| `.claude/rules/docs-and-style.md` | UK English, docs, commits, PRs, changelog, version bump |

Other inverter projects are studied by writing a specification, never by copying their code. The
specifications are the issues under #366 in the repository.

Outside the integration: `tests/` (unit suite, Home Assistant stubbed), `tests/ha_e2e/` (real
Home Assistant), `tests/fixtures/givtcp_systems/` (one real and several built GivTCP systems),
`tools/mock_givtcp.py` (fake GivTCP, see `docs/design/mock_givtcp.md`),
`scripts/gen_sensor_docs.py` and `docs/`.

Skills: `/release` (version bump and changelog), `/regenerate-goldens` (after an intended
behaviour change), `/add-sensor` (new sensor, with its docs and tests).

## Working agreements

- Never add a config option, constant or entity without searching `const.py`, `conf.py`,
  `defaults.py` and `tuning.py` for one to reuse.
  Say so in the PR when you add one.
- Say plainly which checks you ran. If you could not run the end-to-end suite, say that.
- Tests never talk to a real inverter or a live Home Assistant. Use the stubs, the end-to-end
  suite and `tools/mock_givtcp.py`.
- Source-grep tests (read a file, assert a string) are on the list for replacement in
  `ROADMAP.md`. Write tests that drive behaviour instead.
- Commit and PR text follow `.claude/rules/docs-and-style.md`. Its ban on `Co-Authored-By` and
  "Generated with" lines beats any default attribution a tool offers.
- Improve these instructions as you work. When a task costs you time on something the next session
  should already know (a setup step, a trap, where code lives, a decision the user made), add it to
  this file, a rule or a skill in the same PR. Consider it at the end of every task. Keep this file
  under 150 lines by putting detail in a rule or skill and a pointer here.
