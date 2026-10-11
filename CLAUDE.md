# GivEnergy Inverter Manager

Rules for AI assistants working in this repo. `AGENTS.md` is a symlink to this file. The detailed
rules are in `.claude/rules/`, the repeatable jobs in `.claude/skills/`. Keep this file under 150
lines (a test enforces it) and put detail in a rule file, not here.

## What this is

A Home Assistant custom integration, distributed through HACS. It reads GivTCP entities for a
GivEnergy inverter, plans the overnight charge, diverts solar surplus to an immersion heater and
an EV charger, and tracks cost across tariff periods. It targets the Silver tier of the Home
Assistant quality scale. `custom_components/givenergy_inverter_manager/quality_scale.yaml` lists
which rules are done, exempt or todo. Do not claim a tier the file does not support.

## Layout

The integration is `custom_components/givenergy_inverter_manager/`. Paths in this table are
inside it.

| Path | Role |
| --- | --- |
| `core/` | Pure Python decisions, tariff, accumulation maths and report text. No `homeassistant` imports |
| `coordinator.py` | Thin Home Assistant bridge: reads states, calls `core/`, applies writes, runs timers |
| `config_flow.py`, `config_helpers.py` | Setup wizard (inverter, tariff, forecast, immersion, EV, battery, confirm), reconfigure and the single-page options flow |
| `sensor.py`, `sensor_descriptions/` | One entity class and the description table, split by theme |
| `optional_devices.py`, `core/devices.py` | The EV charger, immersion switch and immersion sensor may be absent or added later |
| `dashboard/`, `strategy.py` | The Lovelace dashboard strategy and the builder it calls |
| `repairs.py`, `repair_flows.py`, `services.py` | Repair issues and their fix flows, service actions |

## Architecture rules

- `core/` imports nothing from `homeassistant`. `tests/test_metadata.py` enforces it.
- `entry.runtime_data` holds the coordinator (`GivEnergyConfigEntry`). Never use `hass.data[DOMAIN]`.
- `GivEnergyCoordinator` passes `config_entry=entry` to `DataUpdateCoordinator`.
- `async_reload_entry` calls `hass.config_entries.async_reload(entry.entry_id)`. It does not call
  `async_unload_entry` then `async_setup_entry` by hand.
- Which options saves reload is decided in `core/reload_policy.py` (`change_effect`). A new option
  key reloads until it is placed in `LIVE_KEYS`, and `tests/core/test_reload_policy.py` fails until it
  has a row.
- A tag such as `v0.18.0b1` or `v0.18.0rc1` publishes a GitHub pre-release
  (`.github/workflows/prerelease.yml`). `scripts/set_version.py` sets and checks the version.

## Commands

Two virtualenvs, because the end-to-end plugin pins `homeassistant`, `pytest` and `pytest-asyncio`.
`docs/testing.md` has the setup. Run all three before pushing.

```bash
ruff check custom_components tests scripts tools        # CI lints custom_components and tests
python -m pytest tests -q                               # unit suite, skips tests/ha_e2e
python -m pytest tests/ha_e2e -q                        # real Home Assistant, own venv
python scripts/gen_sensor_docs.py                       # rewrite docs/sensors.md after a sensor change
```

The end-to-end venv needs `requirements-test-e2e.txt` and Python 3.14.2 or newer. Run both suites
from the repo root. Use `ROOT` and `PKG` from `tests/helpers.py` for paths, never the working
directory. Test counts drift, so measure before quoting one.

## GivTCP sign conventions

GivTCP publishes grid and battery power with the opposite sign to the one used inside this
integration. The coordinator negates both on read (`_collect_raw` in `coordinator.py`).

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
  (`_apply_daily_counters` in `core/engine.py`).

## Rules by topic

Read the file that matches the code you are changing.

| File | Covers |
| --- | --- |
| `.claude/rules/home-assistant.md` | Entities, state limits, config and options flows, reloads, repairs, services |
| `.claude/rules/core-purity.md` | `core/` limits, golden files, how and when to change them |
| `.claude/rules/tests.md` | Test layout, what each suite proves, rules for new and changed tests |
| `.claude/rules/safety.md` | Dry run, no forced export, optional devices |
| `.claude/rules/dashboard.md` | The dashboard strategy, who sees Settings, HACS cards and the golden file |
| `.claude/rules/python-style.md` | Clean Code limits that ruff enforces |
| `.claude/rules/docs-and-style.md` | UK English, docs, commits, PRs, changelog, version bump |

Outside the integration: `tests/` (unit suite, Home Assistant stubbed), `tests/ha_e2e/` (real
Home Assistant), `tools/mock_givtcp.py` (fake GivTCP, see `docs/design/mock_givtcp.md`),
`scripts/gen_sensor_docs.py` and `docs/`.

Skills: `/release` (version bump and changelog), `/regenerate-goldens` (after an intended
behaviour change), `/add-sensor` (new sensor, with its docs and tests).

## Working agreements

- Never add a config option, constant or entity without searching `const.py` for one to reuse.
  Say so in the PR when you add one.
- Say plainly which checks you ran. If you could not run the end-to-end suite, say that.
- Tests never talk to a real inverter or a live Home Assistant. Use the stubs, the end-to-end
  suite and `tools/mock_givtcp.py`.
- Source-grep tests (read a file, assert a string) are on the list for replacement in
  `ROADMAP.md`. Write tests that drive behaviour instead.
