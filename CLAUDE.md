# CLAUDE.md — GivEnergy Inverter Manager

This file gives AI assistants (Claude Code, MCP tools, Copilot) the context needed to
make good decisions when working on this repo.

---

## What this is

A Home Assistant custom integration for GivEnergy inverters. It reads sensor data from
GivTCP over MQTT, calculates overnight charge targets, manages solar surplus diversion
to immersion and EV, and tracks energy costs across tariff periods.

The integration is distributed via HACS. It works towards the HA quality scale Silver tier
but does not meet it yet: `quality_scale.yaml` has Bronze `config-flow-test-coverage` and Silver
`test-coverage` as `todo` (94% combined coverage against the 95% the rule needs). Every other
Bronze and Silver rule is `done` or exempt.

---

## Key architecture decisions

**core/ is pure Python with no HA imports.** All business logic lives in
`custom_components/givenergy_inverter_manager/core/`. Nothing there imports from
`homeassistant.*`. This makes it fully unit-testable without a running HA instance.

The HA layer (coordinator, sensor, switch, number) is thin — it reads from GivTCP,
calls core functions, and writes results back.

**`entry.runtime_data`** holds the coordinator. Never use `hass.data[DOMAIN]`.

**`DataUpdateCoordinator`** requires `config_entry=entry` in `super().__init__()` when
calling `async_config_entry_first_refresh()` in HA 2026.7+.

**Coordinator update callbacks must be sync `@callback` functions.** If a callback needs
an async service call, schedule it with `hass.async_create_task()`. `async def` callbacks
create unawaited coroutines and silently do nothing.

**`async_reload_entry` must delegate to `hass.config_entries.async_reload(entry.entry_id)`.**
Calling `async_unload_entry` + `async_setup_entry` directly bypasses HA's state machine
and causes entities to go unavailable after an options save.

---

## GivTCP sign conventions

GivTCP publishes sensor data with these sign conventions:

| Sensor | Positive | Negative |
| --- | --- | --- |
| `grid_power` | **export** to grid | import from grid |
| `battery_power` | **discharging** | charging |
| `solar_power` | always positive | n/a |

**GivTCP v3 uses positive=export for grid power.** The coordinator negates this on read
so that `RawReading.grid_power_w` follows the HA/internal convention (positive=import).
**GivTCP battery power is positive=discharging.** The coordinator negates it on read too, so
`battery_power_w` is positive=charging everywhere inside the integration (engine, rules, EV,
sensors). GivTCP's own `battery_charge_energy_today_kwh` / `battery_discharge_energy_today_kwh`
counters are read by those names.
The test `test_reads_grid_power_negative_when_exporting` passes "+1200" from GivTCP
and asserts raw value is -1200 (after negation).

Without the negation, the engine accumulates all grid exports as imports, inflating
import costs and causing the power-flow-card-plus to show 9x the expected home load
(solar + "import" instead of solar - export).

The `house_load_w` sensor is read directly from GivTCP's load measurement, not
calculated. It only reflects the inverter-side load, not total mains consumption —
this is expected behaviour and matches what GivTCP reports.

**GivTCP daily energy counters** (`pv_energy_today_kwh`, `import_energy_today_kwh`,
`export_energy_today_kwh`, `charge_energy_today_kwh`, `discharge_energy_today_kwh`,
`load_energy_today_kwh`) are read from the inverter serial derived entity IDs and used
as the authoritative source for today's kWh values. The coordinator reads these via
`_collect_raw` and `_apply_daily_counters` overrides the integration-accumulated values
after each cycle. Falls back silently to integration if entities are absent.

**The Zappi (myenergi) and GivEnergy inverter are separate systems.** The Zappi uses
its own CT clamp and there is no integration between them. For a Zappi with a charge
mode select entity, the integration switches it to Eco+ (never Stopped or Fast) when a
car is plugged in and net solar surplus is at least `EV_CHARGER_MIN_POWER_W`
(`_apply_ev_action` in `coordinator.py`; skipped in dry run, read-before-write, and
subject to the `GIVTCP_MIN_WRITE_INTERVAL_S` write cooldown). It never stops or pauses
the Zappi. It also surfaces `ev_solar_surplus_available`, `ev_charging_source`, and
`ev_draining_battery` as signals for user automations, and for chargers it cannot
control.

---

## HA selector constraints

`NumberSelectorConfig` enforces `step >= 0.001` via voluptuous. Steps smaller than this
(e.g. `step=0.0001`) fail silently during config flow validation. Always use `step=0.001`
or larger.

`TimeSelector` returns `HH:MM:SS`. The rate period helpers strip `:SS` on save
(`[:5]`) and add `:00` on load (`_hhmmss()`).

`section()` from `homeassistant.data_entry_flow` only supports one level of nesting.
Rate period sections in the options flow sit at the top level alongside `tariff_settings`,
`threshold_settings`, and `forecast_settings` — not nested inside `tariff_settings`.

---

## Config flow structure

**Initial setup (7 steps):**
`inverter` → `tariff` → `forecast` → `immersion` → `ev` → `battery` → `confirm`

The tariff step uses `_build_tariff_schema(periods)` which includes up to 5 rate period
sections. Rate periods are stored as `list[dict]` with keys `name`, `rate`, `start`,
`end` (HH:MM strings).

**Options flow (single page):**
`async_step_init` — one page with collapsible sections. Rate period sections are at the
top level (not inside `tariff_settings`). On submit, rate periods are read from
top-level `user_input.get("rate_period_N")` via `_slots_to_rate_periods(user_input)`.

---

## Sensor state_class rules

HA 2026.7+ rejects `state_class=MEASUREMENT` on monetary or certain energy sensors:

- Monetary sensors that accumulate: use `TOTAL`
- Monetary sensors that are estimates/projections: use `None`
- Energy sensors that reset daily: use `TOTAL` (not `TOTAL_INCREASING` — they reset)
- Any `TOTAL` sensor that resets must report `last_reset`: `is_daily_total=True` or
  `reset_period="week"|"month"|"year"` on the description. `test_sensor_integrity.py` enforces this
- Yesterday, trailing 12-month and forecast sensors are not cumulative: use `None`
- Live power sensors: use `MEASUREMENT`

---

## Testing approach

Two suites, two virtualenvs. Run both before pushing.

```bash
# Stubbed unit suite: about 2340 tests in about 13 s
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q          # pyproject.toml skips tests/ha_e2e
.venv/bin/python -m ruff check .

# Real Home Assistant suite (tests/ha_e2e): about 190 tests in about 17 s
python3 -m venv .venv-e2e                    # needs Python 3.14.2 or newer
.venv-e2e/bin/pip install -r requirements-test-e2e.txt
.venv-e2e/bin/python -m pytest tests/ha_e2e -q
```

The unit tests use MagicMock stubs for most HA imports (see `tests/conftest.py`) and run from
any directory. Use `ROOT` and `PKG` from `tests/helpers.py` for source paths, never a path
relative to the working directory. A real `homeassistant` package is installed for the schema
tests in `tests/test_config_flow_schemas.py`, which catch selector constraint violations that
MagicMock stubs would silently pass.

The e2e suite needs its own virtualenv because `pytest-homeassistant-custom-component` pins
`homeassistant`, `pytest` and `pytest-asyncio`. Run it from the repo root. `tests/ha_e2e/pytest.ini`
is the closest ini file, so `tests/conftest.py` (the stubs) never loads. `docs/testing.md` has
the detail. The test counts above drift, so re-measure before quoting them.

Prefer a test that drives behaviour (a coordinator, entity or flow call and an assertion on the
result) over one that reads a source file and asserts a string is present. The remaining
source-grep tests are listed for replacement in `ROADMAP.md`.

**Before adding a new sensor:** add tests in `tests/test_sensors.py` covering
device_class, unit, state_class, and value_fn. The existing battery_power tests
are the reference pattern. Put any value logic longer than one expression in
`sensor_values.py` (pure, no HA imports) and test it in `tests/test_sensor_values.py`. Then run
`python scripts/gen_sensor_docs.py` to refresh `docs/sensors.md`.

**Before changing config flow schemas:** run `tests/test_config_flow_schemas.py` with
the real HA package, which catches `step` constraints, selector validation, and
section nesting issues, then the e2e config flow tests.

**Version bumps** must change `manifest.json`, `const.INTEGRATION_VERSION`, `pyproject.toml`,
the `Current version:` line in `README.md` and the `This documentation matches version` line in
`docs/index.md` together. `tests/test_metadata.py` fails if one is missed.

---

## Code standard (Clean Code)

The code follows Robert C. Martin's *Clean Code*. Ruff enforces the measurable parts in `pyproject.toml`: complexity 8, 30 statements, 4 arguments, no boolean flag parameters. New code must stay inside the limits. An existing offender carries an inline `# noqa: <rule>` marker, and the change that fixes the function deletes the marker.

- A function does one thing at one level of abstraction. Aim for 20 lines or fewer, never more than 40. Extract until each function reads as a short paragraph.
- Name things for what they mean (`available_surplus_w`, not `calc2`). A comment says why, never what the next line does. Delete commented-out code.
- Three arguments or fewer is the goal. A longer list becomes a named parameter object (a frozen dataclass). A boolean flag argument means the function does two things: split it, or use an enum.
- A function either changes state (a command) or returns a value (a query), not both.
- A class has one reason to change. When a class mixes reading state, deciding and writing to hardware, split it.
- Prefer raising an exception to returning an error code. Do not return or pass `None` when an empty value or a null object works.
- Pure logic lives in `core/` and imports nothing from Home Assistant. Home Assistant glue stays thin.
- No duplication: when you copy a block a second time, extract it.
- Refactor in small steps with the tests green. For code without tests, pin today's behaviour with a characterisation test first, then change it.
- Home Assistant schemas and entity description tables are declarative on purpose and may stay long. Keep the logic out of them.

## Pull requests and branches

- Titles and commits follow Conventional Commits (`fix(sensor): ...`).
- The PR description uses `.github/PULL_REQUEST_TEMPLATE.md`: Summary, Changes, Testing,
  Impact, Checklist. This repo does not use a BRAVE section.
- Work is often stacked: each PR is based on the branch below it (`--base <previous-branch>`),
  not on `main`. To take changes from a lower branch, merge it in. Do not rebase or force-push a
  branch that has an open PR. When a lower PR merges, retarget the next one to `main`.
- Address review feedback with new commits on top, so reviewers see only what changed.
- CI runs on every PR: lint and unit tests, the real Home Assistant suite, Hassfest, HACS and
  CodeQL. See `docs/testing.md`.

---

## Dashboard

The dashboard is generated by a HA service (`givenergy_inverter_manager.get_dashboard_yaml`)
defined in `dashboard.py`. The builder lives in `dashboard_builder.py`. It builds a dict and
serialises it with PyYAML, so never hand-indent YAML in an f-string.

The builder looks entity IDs up in the entity registry (`_Registry.get`), so IDs in the
generated YAML are always current. A row or card is included only when its entity is
registered and enabled. EV, immersion, inverter temperature and forecast rows also need the
feature configured. `docs/dashboard-example.yaml` is a golden file: after a deliberate change,
run `UPDATE_DASHBOARD_EXAMPLE=1 python -m pytest tests/test_dashboard_example.py` and review
the diff.

The power flow card (view 1) requires `power-flow-card-plus` from HACS, and the immersion
charts need `apexcharts-card`. If the Lovelace resource list is readable and lacks them, the
builder uses built-in cards instead. The battery `entity` field of the power flow card must be
the **battery power sensor** (watts), not the SoC sensor. Using SoC gives the card a % value as
watts and distorts all flow calculations.

Sensors that reset at midnight are plotted with `statistics-graph` (change per period), not
`history-graph`, which draws a sawtooth. Energy today tiles and glance rows use the entity
state, not a `statistic` card: `stat_type: change` gives negative values on a fresh install.

## Known limitations / open questions

- **Import vs export on dashboard:** The integration correctly tracks import and export
  using GivTCP's `grid_power` sensor. However, GivTCP only measures the inverter-side
  grid connection. Loads wired directly to the main consumer unit (bypassing the inverter)
  will appear as grid import even when solar is generating. This is a GivTCP/hardware
  limitation, not an integration bug.

- **Battery power sign:** GivTCP's `battery_power` entity is positive=discharging, negative=charging
  (confirmed live on a GivTCP 3.5 Gen3 hybrid: -3.4 kW during the overnight charge as SoC rose).
  The coordinator negates it on read, so the **Battery Power** entity of this integration is
  positive=charging. A card that reads GivTCP's raw entity needs the opposite sign handling.

---

## Files that should not be edited without reading first

| File | Why |
| --- | --- |
| `core/engine.py` | Contains the charge algorithm and accumulation logic. Sign conventions documented inline. |
| `core/rules.py` | Business rules for divert decisions. Each function has a docstring explaining the logic. |
| `config_flow.py` | Config and options flow. HA section nesting constraints mean rate periods must be top-level. |
| `coordinator.py` | Thin HA bridge. `_collect_raw()` reads GivTCP entities; `_run_cycle()` calls core functions. |
