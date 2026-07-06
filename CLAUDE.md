# CLAUDE.md — GivEnergy Inverter Manager

This file gives AI assistants (Claude Code, MCP tools, Copilot) the context needed to
make good decisions when working on this repo.

---

## What this is

A Home Assistant custom integration for GivEnergy inverters. It reads sensor data from
GivTCP over MQTT, calculates overnight charge targets, manages solar surplus diversion
to immersion and EV, and tracks energy costs across tariff periods.

The integration is distributed via HACS and targets HA quality scale Silver.

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
| `battery_power` | charging (verify per model) | discharging |
| `solar_power` | always positive | n/a |

**GivTCP v3 uses positive=export for grid power.** The coordinator negates this on read
so that `RawReading.grid_power_w` follows the HA/internal convention (positive=import).
The test `test_reads_grid_power_negative_when_exporting` passes "+1200" from GivTCP
and asserts raw value is -1200 (after negation).

Without the negation, the engine accumulates all grid exports as imports, inflating
import costs and causing the power-flow-card-plus to show 9x the expected home load
(solar + "import" instead of solar - export).

The `house_load_w` sensor is read directly from GivTCP's load measurement, not
calculated. It only reflects the inverter-side load, not total mains consumption —
this is expected behaviour and matches what GivTCP reports.

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

**Initial setup (6 steps):**
`inverter` → `tariff` → `forecast` → `immersion` → `ev` → `battery`

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
- Live power sensors: use `MEASUREMENT`

---

## Testing approach

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -q          # full suite (~400 tests)
ruff check custom_components/ tests/
```

Tests use MagicMock stubs for most HA imports (see `tests/conftest.py`). A real
`homeassistant` package is installed for schema validation tests in
`tests/test_config_flow_schemas.py` — these catch selector constraint violations that
MagicMock stubs would silently pass.

**Before adding a new sensor:** add tests in `tests/test_sensors.py` covering
device_class, unit, state_class, and value_fn. The existing battery_power tests
are the reference pattern.

**Before changing config flow schemas:** run `tests/test_config_flow_schemas.py` with
the real HA package — this catches `step` constraints, selector validation, and
section nesting issues.

---

## Dashboard

The dashboard is generated by a HA service (`givenergy_inverter_manager.get_dashboard_yaml`)
defined in `dashboard.py`. It uses `e(suffix)` to look up entity IDs from the entity
registry at runtime, so entity IDs in the generated YAML are always current.

The power flow card (view 1) requires `power-flow-card-plus` from HACS. The battery
`entity` field must be the **battery power sensor** (watts), not the SoC sensor. Using
SoC gives the card a % value as watts and distorts all flow calculations.

Energy today cards use `type: entity` (not `type: statistic`). The daily sensors already
accumulate from midnight and reset at midnight — using `statistic` with `stat_type: change`
gives negative values on a fresh install.

---

## Known limitations / open questions

- **Import vs export on dashboard:** The integration correctly tracks import and export
  using GivTCP's `grid_power` sensor. However, GivTCP only measures the inverter-side
  grid connection. Loads wired directly to the main consumer unit (bypassing the inverter)
  will appear as grid import even when solar is generating. This is a GivTCP/hardware
  limitation, not an integration bug.

- **Battery power sign:** GivTCP's `battery_power` entity: positive=charging in the
  GIV-HY-5.0 setup. This was confirmed by test. If a different GivEnergy inverter model
  uses the opposite convention, the battery charge/discharge accumulation will be wrong.

---

## Files that should not be edited without reading first

| File | Why |
| --- | --- |
| `core/engine.py` | Contains the charge algorithm and accumulation logic. Sign conventions documented inline. |
| `core/rules.py` | Business rules for divert decisions. Each function has a docstring explaining the logic. |
| `config_flow.py` | Config and options flow. HA section nesting constraints mean rate periods must be top-level. |
| `coordinator.py` | Thin HA bridge. `_collect_raw()` reads GivTCP entities; `_run_cycle()` calls core functions. |
