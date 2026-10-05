# GivEnergy Inverter Manager — Roadmap

Organised by theme and priority.

---

## Current State (v0.3.0)

### What is built and working

- **GivTCP auto-discovery** — scans HA for `sensor.givtcp_{SERIAL}_*` entities and
  pre-fills the setup form
- **Multi-brand EV charger discovery** — Zappi (myenergi), Wallbox, Ohme, Easee, OCPP
- **EV drain detection** — `ev_draining_battery` sensor detects when the EV charger
  is drawing from the battery rather than solar or grid; `ev_charging_source`
  (Solar/Grid/Battery/Mixed) shows the live source; `ev_solar_surplus_available`
  triggers Zappi Eco+ automation when surplus exceeds 1,400W
- **Overnight charge calculator** — uses Forecast.Solar or Solcast (or seasonal
  fallback) to decide how much to charge from grid overnight; skips charging entirely
  when battery is high and forecast is strong
- **Charge write-back to GivTCP** — at the start of the cheapest rate window the
  integration writes the recommended target SoC directly to the inverter via
  `number.givtcp_{SERIAL}_target_soc`
- **Solar surplus → immersion divert** — turns on immersion heater when battery is
  full and solar is generating surplus; respects water temperature limits
- **Appliance run suggestions** — advises when to run high-load appliances based on
  solar surplus and tariff
- **Full financial P&L** — import cost per rate period, export earnings,
  self-consumption value, per-load cost breakdown (EV, immersion, rest of house)
- **Bill prediction** — accrued bill, projected total, days remaining, using
  standing charge, PSO levy, VAT, and supplier discount correctly
- **Persistent energy accumulators** — today/week/month/yesterday data survives HA
  restarts via HA Storage
- **Battery health tracking** — cycle count, remaining life %, days since full charge,
  estimated years remaining
- **Night survival prediction** — estimates SoC at sunrise and warns if battery may
  run out before solar starts
- **Dynamic multi-rate tariff** — any number of rate periods including overnight
  (e.g. Night 23:00–08:00 with Nightboost 02:00–04:00 override); editable via
  options flow without reinstalling
- **Correct DST/timezone handling** — all rate period comparisons use HA's configured
  local timezone; rate periods activate at the correct local time year-round
- **Forecast accuracy tracking** — yesterday's accuracy and 7-day rolling average;
  auto-fallback to seasonal estimate when accuracy is poor
- **Configurable currency** — EUR, GBP, USD, SEK, NOK, DKK, AUD, CAD, NZD, ZAR
- **Immersion run-to-target** — when the immersion is switched on (manually, via
  automation, or physical button) it runs until the water reaches the configured target
  temperature, then releases back to auto; external turn-off applies a 10-minute cooldown
  before auto-divert can resume
- **Immersion cooldown** — a 10-minute cooldown between automatic on/off writes prevents
  rapid cycling caused by brief solar surplus fluctuations
- **Free battery discharge overnight** — when the integration decides to skip overnight
  charging it writes the minimum SoC target to GivTCP so the battery can discharge freely
  rather than holding at the old target and importing from grid
- **Dashboard writes to file** — `get_dashboard_yaml` writes `givenergy_dashboard.yaml`
  directly to the HA config directory; placeholder created on setup so YAML-mode
  dashboards load immediately; **Refresh Dashboard** button regenerates on demand
- **Inverter temperature derating** — auto-discovers `givtcp_*_invertor_temperature`;
  surfaces `inverter_temperature`, `inverter_temperature_status` (Normal/Warm/Derating/Critical),
  and `inverter_derating_today_minutes` (disabled by default)
- **EV solar charging signal** — `ev_charging_source` (Solar/Grid/Battery/Mixed) and
  `ev_solar_surplus_available` (Available/Not available) for Zappi Eco+ automation triggers
- **Missed solar opportunity** — `missed_solar_today` accumulates kWh exported while
  battery is full and no flex load is active (disabled by default)
- **Predictive immersion scheduling** — runs immersion during cheap rate when tomorrow's
  forecast is below 5 kWh, ensuring hot water on overcast days
- **Solar noise floor** — sensor readings below 10W are ignored during accumulation,
  preventing overnight noise from inflating `solar_today`
- **Solcast multi-array** — optional second forecast entity summed with the first for
  east/west facing array installations
- **Live grid cost rate** — `live_grid_cost_rate` sensor (€/hr) shown on the power flow
  card grid node using correct import/export rates; replaces static tariff rate display
- **About 145 sensors**, most of the newer ones disabled by default
- **Dashboard generator** — 4-tab dashboard; live cost rate on grid node; new sensors in
  Battery Health (inverter temp) and Controls EV (charging source, solar surplus)
- **HACS-ready** — `hacs.json`, `manifest.json`, `strings.json`, `translations/en.json`,
  `icons.json` with MDI icons for all entities
- **Repair issues** — `givtcp_entities_missing` repair issue surfaces in Settings → System
  → Repairs when configured GivTCP entities are absent from HA
- **Automation examples** — `docs/automations.md` with 10 ready-to-use HA automation
  examples including Zappi Eco+ and inverter derating alert
- **More than 950 unit tests and 43 real Home Assistant end-to-end tests**

---

## Near-Term (v0.2.x) — remaining

### 95% test coverage target

A real Home Assistant end-to-end suite (`tests/ha_e2e/`, using
`pytest-homeassistant-custom-component`) now covers setup, unload, the config and
options flows, every sensor and midnight `last_reset`. What remains is to measure
coverage across both suites, raise `config_flow.py` coverage, and replace the
source-text assertions in `tests/test_swicth.py` and `tests/test_untested_modules.py`
with behavioural tests.

**Complexity:** Medium.

- **Currency unit as ISO 4217 code:** monetary sensors use the currency symbol as their unit, but Home Assistant expects a code such as `EUR`. Changing it breaks existing long-term statistics, so it needs a one-off statistics repair or migration first. See `docs/long-term-statistics.md`.

---

## Near-Term — Completed ✅

All of the following were planned as near-term and have shipped:

| Item | PR |
|---|---|
| entity-unavailable quality scale | #35 |
| Reconfiguration flow | #36 |
| exception-translations and icon-translations | #36–#38 |
| Solcast multi-array support | #60 |
| Inverter temperature derating sensors | #50, #56 |
| EV solar charging signal | #51 |
| Missed solar opportunity sensor | #52 |
| Predictive immersion scheduling | #61 |
| Solar noise floor fix | #56 |
| Live grid cost rate sensor | #57 |
| Dashboard file write + auto-init | #49, #59 |
| Automation examples | #39, #58 |
| repair-issues quality scale | #40 |
| strict-typing quality scale | #42 |
| Register write safety (read-before-write, retry, write counter) | #77 |
| EMA solar smoothing | #77 |
| EV charger minimum power guard (1,380W) | #77 |
| Seasonal charge bypass (winter/shoulder months) | #77 |
| Minimum write interval per entity (5 min cooldown) | #78 |
| Monthly and annual export volume tracking (12-month snapshots, trailing 12-month sensors) | #90 to #93 |
| Real Home Assistant end-to-end test suite | #126 |

---

## Backlog from external research and bill reconciliation (October 2026)

Sources: a reconciliation of five real electricity bills against the integration, and
a code review of GivTCP, Predbat, the Octopus Energy integration, cdpuk/givenergy-local,
EMHASS, evcc, OpenEMS, solar_optimizer, PV Excess Control, powercalc and Home Assistant
core. Only findings checked in code or documentation are listed. Status: **done** means
merged, **in progress** means a branch exists, **backlog** means not started.

**Pull requests for the items marked in progress.** They form one stack, merged in this order.

| PR | Covers |
|---|---|
| 129 | EV cost: Zappi entities with no serial in the id, charging detection |
| 130 | Bounded immersion hold, one EV threshold, dead EV code, Zappi write cooldown |
| 131 | Per-slot load profile, forecast accuracy correction, day-after-tomorrow forecast, no-solar counterfactual |
| 132 | Bill sensors, flat PSO levy, billing period days, bill start day from options, rate period validation, `compare_tariff` |
| 133 | `last_reset` for week, month and year sensors, year totals saved, restart across a boundary, durable storage |
| 134 | Equivalent-full-cycle count, BMS seeding, write error handling, charge target clamp, write count saved |
| 135 | Labels and help for every config field, slider reloads, reconfigure, options ordering, setup summary |
| 136 | Diagnostics redaction, repair links, services registered once, translation drift, CI and metadata |
| 138 | Dashboard: Now strip, Bill view, empty states, fallbacks, example, optional strategy |

**Order of work.** The direction of this roadmap is sound, but the accounting and test
foundations come before new optimisation features. Finish the items under Accuracy and
Platform quality first, then Forecast and planning, then new hardware support.

### Accuracy (bill reconciliation)

Import kWh matched the bill to 0.1 kWh once the 16th-to-15th billing window was
aligned. Cost was about 9% low because the tariff in the options had not been updated
after the supplier's price change on 1 July.

| Item | Status |
|---|---|
| Reject zero-length and duplicate rate periods in setup and options, and skip them when building the tariff (a 00:00 to 00:00 slot with rate 0 became the "cheapest rate") | in progress |
| PSO levy is a flat monthly amount on the bill, not prorated by days | in progress |
| Bill start day off by one on the start day; read it from the saved options, not only the setup data; document that it is the first day of the billing period | in progress |
| `accrued_bill` and `projected_bill` are computed from today's import cost instead of the billing period (live: EUR 21 against EUR 104 for the month) | in progress |
| `compare_tariff` compared unlike quantities (no supplier saving or VAT on the alternative, standing charge on one side only) | in progress |
| Dated tariff changes: apply a new rate set from an effective date, with a repair when rates have not been reviewed for a long time | backlog |
| A calibration service to match the integration's totals to a supplier bill (powercalc `calibrate_cost` is the model) | backlog |
| Export reads about 2% above the supplier meter (inverter-side measurement); document it | backlog |
| Live tariff comparison across plans (issue 114): needs a persisted per-slot (30 minute) import and export accumulator first | backlog |

### Battery

| Item | Status |
|---|---|
| Cycle count counts charge and discharge, so it runs about 1.6 times the BMS counter; count discharge only and seed from the GivTCP BMS cycle counter | in progress |
| `Battery Life Consumed Today` read twice its real value | done |
| State of health sensor from the GivTCP calibrated and design capacity, and battery temperature | backlog |
| Include round-trip efficiency and cycle cost in the pre-boost export gain (evcc uses 0.9 per direction; EOS uses a levelised cost of storage) | backlog |
| Persist the register write count and read GivTCP's own write count when present | in progress |

### Inverter writes

| Item | Status |
|---|---|
| Cheap-rate floor write bypassed the cooldown, read-back and write counter | done |
| A failed service call aborts the five-step charge-target sequence before the enable switch; clamp targets to 4 to 100 (GivTCP's own range); key the cooldown on entity and value | in progress |
| Zappi mode writes have no cooldown | in progress |

### Control logic

| Item | Status |
|---|---|
| Immersion surplus collapsed once the element switched on, so it flapped | done |
| Hold or refuse to start on unavailable sensors | done |
| Bound the hold during a long outage | in progress |
| EV energy and cost never worked: Zappi discovery assumed the serial was in the myenergi entity ids, and charging was never detected because only the plug status sensor was read (PR 129) | in progress |
| Use the Zappi's own energy counters (`green_energy_today`, `energy_used_today`, `charge_added_session`) as the authority for EV energy, and split EV cost into solar and grid shares; today the cost is the EV's share of inverter-side grid import, so it accrues only while the house imports | backlog |
| Remove dead EV code and the three overlapping EV thresholds | in progress |
| On and off delays on sustained conditions rather than only a write lockout (evcc: enable 1 minute, disable 3 minutes; solar_optimizer: minimum on and off durations) | backlog |
| Smooth the net surplus, not only solar, and seed the average from the first reading | backlog |
| Periodic pasteurisation cycle for the hot water cylinder, separate from the minimum temperature floor (needs the owner's confirmation of target temperature) | backlog |
| Deadline heating: reach a temperature by a set time using the cheapest tariff window (OpenEMS heating element controller) | backlog |
| Priority arbitration when EV and immersion compete for the same surplus (evcc prioritiser) | backlog |
| EV departure-time plan over the tariff windows, as a signal for automations (evcc planner) | backlog |
| Charger minimum power depends on phases: 1,380 W is correct for single phase only | backlog |

### Forecast and planning

| Item | Status |
|---|---|
| The learned per-slot load profile is not used by the charge calculation and is lost on restart; persist it and use it | in progress |
| Forecast accuracy is measured but never fed back; scale the forecast by a clamped median actual to forecast ratio (evcc `solarScale`; EMHASS adaptive conformal inference) | in progress |
| The day-after-tomorrow forecast does not reach the engine | in progress |
| Slot-shaped solar curve from a per-period forecast attribute instead of a fixed bell curve (uncertain: depends on what the Solcast integration exposes) | backlog |
| Dynamic day-ahead tariffs: the supplier and regulator timeline needs a verified source before this is planned | backlog |

### Platform quality

| Item | Status |
|---|---|
| Daily sensors used `TOTAL_INCREASING` with `last_reset`, which Home Assistant rejects, so their values froze | done |
| Duplicate `export_trailing_12m`, invalid state classes on the pre-boost sensors, missing translations | done |
| Options form reverted saved zero and cleared values; empty entity selectors blocked saving | done |
| Manual setup path crashed | done |
| Week, month and year sensors need `last_reset`; yesterday, rolling and projected sensors should have no state class; persist year totals; flush accumulators on shutdown | in progress |
| Monetary unit is a currency symbol; Home Assistant expects an ISO 4217 code. Changing it breaks existing statistics, so it needs a migration plan | backlog |
| Diagnostics redact nothing, repairs have no learn-more link, no `_unrecorded_attributes` for the HTML report sensors, translation drift between `strings.json` and `en.json`, services registered per entry instead of once | in progress |
| `hacs.json` minimum Home Assistant version, `pyproject.toml` build backend, nightly CI and a Python matrix, untrack `coverage.json` | in progress |
| Issue templates that require a diagnostics download and the GivTCP version; architecture decision records for the cycle definition and the tariff model | backlog |

### Dashboard and installation

A review of the live dashboard found that a pasted dashboard goes stale, new installs
show "Entity not available" for a disabled sensor, and the actionable facts (battery
level, night survival, next cheap window) sit on different tabs.

| Item | Status |
|---|---|
| Include rows and cards only for entities that are registered and enabled, or for features that are configured | in progress |
| "Now" strip on the first view and a "Bill" view built from core cards, so drift against a real bill is visible | in progress |
| Build the dashboard as a dictionary instead of hand-indented text, with a golden test | in progress |
| Copy-me example dashboard in `docs/`, kept in step by a test | in progress |
| Thin Lovelace strategy (`custom:givenergy-manager`) served by the integration, about 30 lines of plain JavaScript, so the dashboard never goes stale (pattern verified in garmin_connect and WebRTC; Mushroom's strategy shows the support cost of cache and registration problems) | in progress, separate commit that can be dropped |
| Fallback card when `power-flow-card-plus` or `apexcharts-card` is not installed | in progress, if resources can be detected reliably |
| Charge plan timeline card | backlog, build only if core cards cannot express it |
| Integration-owned storage dashboard that rewrites the user's Lovelace | not planned: relies on internal Home Assistant APIs and would overwrite user edits |
| Sidebar panel, a rebuild of power-flow-card-plus or apexcharts, a webpack or TypeScript pipeline | not planned |

### Configuration experience

| Item | Status |
|---|---|
| Label and one-sentence help for every setup, options and reconfigure field, including what 0 or empty means; "First day of your billing period" wording for the bill start day | in progress |
| Immersion temperature sliders reload the whole integration on every move | in progress |
| Reconfigure is overridden by saved options and reloads twice | in progress |
| Options sections ordered by use, tariff expanded by default | in progress |
| Stale-tariff prompt and dated rate changes | backlog, see Accuracy |

### What not to copy

- Predbat source: personal and non-commercial licence in `control_ledger.py`. Reimplement ideas only.
- PV Excess Control (AGPL-3.0), `ecodan_ctrl` (GPL-3.0) and OpenEMS (AGPL-3.0 or EPL-2.0): ideas only.
- Linear programming or genetic optimisers and machine learning forecasters (EMHASS, EOS): too heavy for this integration.
- Unredacted `entry.as_dict()` diagnostics (powercalc) and per-sensor attribute dumps (Tibber).

---

## Medium-Term (v0.3.0)

### Solcast P10/P50 conservatism weighting

The overnight charge target currently uses a single forecast value (P50 median).
Solcast also exposes P10 (pessimistic) and P90 (optimistic) bands. A configurable
`forecast_conservatism` weight (0.0 = pure P50, 1.0 = pure P10) lets the user
dial in how aggressively to hedge against cloudy days.

Triangular blend formula (from pv_opt and EMHASS):
```
wgt_10 = max(0, 0.5 - conservatism) / 0.4
wgt_50 = 1 - abs(conservatism - 0.5) / 0.4
wgt_90 = max(0, conservatism - 0.5) / 0.4
forecast = wgt_10 * p10 + wgt_50 * p50 + wgt_90 * p90
```

Exposed as a slider in the Forecast section of the options flow.
Default: 0.35 (slightly pessimistic, same as PALM default).

**Complexity:** Low — new config key + pass weight through to `rules.py`.

---

### Forward SoC simulation for overnight charge target

Replace the three-tier lookup (strong/moderate/poor forecast) with a physics-based
forward simulation over the next 24–48 hours. Directly implements the PALM algorithm:

1. Build a 48-slot (30-min) profile of estimated solar generation using the
   weighted forecast (P10/P50 blend) and estimated load from historical average.
2. Simulate battery SoC slot-by-slot from start of cheap-rate window.
3. Track `max_charge` (battery peak from solar) and `min_charge` (trough before
   that peak — the worst SoC point during the day).
4. `target_soc = max(100 - max_charge_pct, (min_reserve - min_charge_pct), min_reserve)`

This answers precisely: "what is the minimum overnight charge that ensures the
battery never drops below reserve, even at its worst point during the day?"

Add winter bypass: if current month is in `winter_months` config list (default
Nov–Feb), return 100% immediately without simulation — solar is negligible and
filling the battery is always correct.

Add shoulder-month floor: raise `min_soc` from `battery_min_soc` to
`battery_max_soc` during shoulder months (Mar–Apr, Sep–Oct) when heating load
is variable.

Research source: PALM `compute_tgt_soc()`.

**Complexity:** Medium — requires per-slot load history accumulation (see below);
the simulation itself is ~50 lines of pure Python in `rules.py`.

---

### Per-slot load history accumulation

The forward SoC simulation needs a per-half-hour consumption profile, not just
a daily average. Accumulate the past 7 days of 48-slot consumption in coordinator
state. Weight recent days higher (yesterday=1.0, three days ago=0.5, etc.).

Subtract immersion and EV energy from historical load before averaging to avoid
inflating the baseline with intermittent large loads.

Apply 5% pessimism scaling (`load_scaling = 1.05`) — from Predbat's load scaling.

Apply in-day adjustment: `scale_today = actual_load_so_far / predicted_load_so_far`
— corrects for days that are running hotter or cooler than the weekly average.

**Complexity:** Medium — new accumulator ring buffer in coordinator state.

---

### Overmorrow correction for overnight charge target

After computing tonight's target, simulate two days ahead. If the day-after-tomorrow
would overflow the battery (solar fills it past 100%), reduce tonight's target
proportionally — leaving room for extra solar without wasting grid charge.

```python
if max_charge_pct_day2 > 100 and max_charge_pct_day1 < 100:
    max_charge_pct += int((max_charge_pct_day2 - 100) / 2)
```

~15 lines added to `calculate_overnight_charge_target` in `rules.py`.
Requires two forecast readings (tomorrow + day-after-tomorrow) from Solcast.

Research source: PALM overmorrow function.

**Complexity:** XS (once forward simulation exists).

---

### Battery degradation cost in dispatch decisions

Factor battery cycle cost into the dispatch decision threshold. The integration
currently diverts surplus to immersion and recommends EV charging without
considering whether the resulting battery cycles are economically worthwhile.

Add `battery_cycle_cost_per_kwh` constant derived from the Predbat formula:
```python
cycle_cost_per_kwh = battery_cost / (2 * capacity_kwh * cycle_life)
# e.g. €4,000 / (2 × 19 × 6,000) = 1.75c/kWh per direction
```

Use as a minimum threshold in divert and dispatch decisions: only divert if
the CEG rate foregone exceeds the degradation cost. Exposed as `CONF_BATTERY_COST`
(install cost in €) — new optional config field.

Research source: arXiv 2606.16051 (cost-only optimisers destroy 3–8 years of
battery lifespan); Predbat `metric_battery_cycle` parameter.

**Complexity:** Low — new constant + one comparison in `should_divert_to_immersion`.

---

### Solar ROI and payback calculator

See `improvement-designs.md` Design 5. Enhanced using research findings:

- Use proper net-gain formula: `saving = self_consume_kwh × (import_rate - export_rate)`
  (not just `self_consume_kwh × import_rate` — that ignores lost CEG income)
- Add cycle cost tracking: `battery_life_consumed_pct = total_kwh_cycled / (capacity × rated_cycles)`
- Surface `arbitrage_efficiency` (€ saved per kWh cycled through the battery)
- Add `electricity_price_inflation_pct` config input for long-term projection

New service: `givenergy_inverter_manager.get_roi_summary` returning structured data.

**Complexity:** Medium — template sensors + new service, no coordinator changes.

---

### Counterfactual cost tracking

See `improvement-designs.md` Design 6. The `daily_cost_without_solar` calculation
should use:
```python
counterfactual = load_energy_today_kwh × import_rate  # what you'd have paid without solar
actual = (grid_import_kwh × import_rate) - (export_kwh × export_rate)
saving = counterfactual - actual
```

Include battery cycle cost in `actual` to give a true net saving:
```python
actual_net = actual + total_kwh_cycled_today × cycle_cost_per_kwh
```

**Complexity:** Medium — template sensors + utility meter helpers.

---

### Pre-cheap-rate export opportunity estimator

See `improvement-designs.md` Design 7. Formula refined from research:
```
spare_kwh = current_soc_kwh - evening_load_est_kwh - tomorrow_deficit_kwh
net_gain = spare_kwh × (ceg_rate - boost_rate)
```

On Night Boost: CEG 19.5c vs Boost 9.94c → 9.56c/kWh net gain per kWh
exported before 2am and recharged during Boost. Only recommend if
`net_gain > 0` and `spare_kwh > 1.0`.

**Complexity:** Medium — existing sensor inputs + new binary_sensor + notification.

---

### Monthly and annual export volume tracking

Track export kWh per calendar month and rolling 12-month total. Surface an alert
when export volume justifies renegotiating the CEG rate with the supplier.

**Complexity:** Low — extend the accumulator and add monthly reset logic.

---

### Second immersion element / heat pump water cylinder

Support dual-element cylinders (lower element for solar, upper for backup) and heat
pump hot water units. COP-aware cost calculation for heat pump (1 kWh electricity →
~3 kWh heat).

**Complexity:** Medium.

---

### Storage heater support

Storage heaters are common in Irish homes. Coordinate overnight charging with battery
to prioritise storage heaters during Nightboost when battery is full; track consumption
and estimated heat stored.

**Complexity:** Medium — requires a smart plug or CT clamp on the heater circuit.

---

### Multiple EV charger support

Discover all chargers, track cost per charger, coordinate charging priority.

**Complexity:** Medium.

---

### Tariff comparison tool

Use accumulated real consumption data to model what the bill would have been on
alternative Irish tariffs (Energia, SSE Airtricity, Pinergy). Helps users decide
whether to switch supplier.

**Complexity:** Medium-high — requires modelling other tariffs and hourly consumption.

---

### Year-on-year comparison

Once 12 months of data is collected: compare current month vs same month last year,
flag whether solar + battery is reducing consumption over time.

**Complexity:** Medium — requires 12 months of persisted monthly totals.

---

## Longer-Term (v1.0+)

### GivEnergy administration resilience

GivEnergy entered administration in April 2026. The integration uses local control
via GivTCP (no cloud dependency), but longer-term:

1. **Periodic data export** — CSV/backup of all historical energy and cost data
2. **`givenergy-local` fallback** — detect and use the `givenergy-local` HACS
   integration (by cdpuk, Modbus-based) if GivTCP is unavailable
3. **Migration documentation** — if users move to a different inverter brand, how to
   carry forward tariff and financial history

---

### Heat pump integration

Track ASHP energy consumption, model its interaction with battery charging, adjust
overnight charge target based on cold-weather forecast.

**Complexity:** High.

---

### Demand response / grid stress events

Monitor EirGrid grid frequency or demand response signals. Temporarily halt battery
discharge during grid stress, or export more when the grid needs support.

**Complexity:** High — requires EirGrid API integration.

---

### Carbon intensity optimisation

Use the CO2Signal API to prefer grid import during low-carbon periods (high wind) and
export preferentially during high-carbon periods.

**Complexity:** Low once the decision is made to include it.

---

### Predictive immersion scheduling

If solar is forecast to be low, run the immersion during Nightboost (cheapest rate)
to ensure hot water is available regardless of the day's generation.

**Complexity:** Medium.

---

### Multi-inverter support

Sum solar and battery SoC across multiple GivTCP inverters for homes with gateway +
AIO configurations.

**Complexity:** Medium.

---

## Companion HACS Repositories (post v1.0)

Planned as separate HACS repositories after v1.0 stabilises sensor naming:

- **Power Flow Card** — real-time animated energy flow, pre-configured for this
  integration's entity IDs, zero setup required
- **Energy History Card** — ApexCharts stacked bar chart of daily energy and cost
  history with solar/import/export overlays
- **Charge Plan Timeline Card** — SVG timeline of tonight's charge plan with battery
  SoC trajectory, rate period bands, and forecast solar ramp
- **HTML Report Templates** — pre-built dashboard YAML using the three HTML report
  sensors, with wrapper card for refresh button and last-updated timestamp

These will not be developed until sensor naming is stable at v1.0.

---

## Technical Debt

### Coordinator: energy accumulation precision

The current integration-based accumulation (power × elapsed time) introduces small
errors vs GivTCP's own energy counters (`pv_energy_today_kwh`, `import_energy_today_kwh`
etc.) which are more accurate as they come from the inverter itself. A future version
should prefer GivTCP energy sensors where available, falling back to integration only
when unavailable.

### Config flow: multi-step EV charger configuration

The EV step is a single form. Better UX: show discovered chargers, confirm entity
mapping, ask car-specific questions (efficiency, battery size), test that the charge
mode entity is writable.

### Translations

Only `en.json` exists. Translations for `ga` (Irish), `sv` (Swedish), `nb`
(Norwegian) would be a valuable community contribution.

### `pytest-homeassistant-custom-component`

Done in #126. The stubbed suite in `tests/` is kept for fast logic tests, and the real
Home Assistant suite lives in `tests/ha_e2e/` with its own CI job. See `docs/testing.md`.

---

## Known Limitations

| Limitation | Impact | Status |
|---|---|---|
| Only one EV charger tracked for cost | Multi-EV homes show incomplete cost | Planned v0.3.0 |
| Zappi Eco+ competes with battery for solar | Suboptimal solar allocation | Mitigated by pause/resume; full resolution needs real-time power sharing |
| Forecast.Solar less accurate for east-west arrays | Charge target may be slightly off | Solcast multi-array planned v0.2.0 |
| Bill prediction assumes constant daily usage | Inaccurate early in billing period | Improves over time as more data is collected |
| GivTCP must be installed and running | Hard dependency | Documented; detection in place; `givenergy-local` fallback planned v1.0 |
| Tariff rates are entered by hand | A supplier price change leaves costs low until the options are updated (seen after 1 July 2026) | Dated tariff changes in backlog |
| Cycle count is an estimate from state of charge | Reads higher than the battery's own counter | Fix in progress |
| Monetary sensors use a currency symbol as the unit | Long-term statistics for cost sensors may be rejected by newer Home Assistant versions | Migration plan in backlog |

---

## Changelog

### v0.3.0

Charge optimisation, ROI metrics, and a large set of new sensors and services.

**Charge algorithm**
- **Forward SoC simulation** — replaces the three-tier strong/moderate/poor forecast
  lookup with a 48-slot binary-search simulation (PALM algorithm). Returns the minimum
  overnight charge that keeps SoC above `min_soc` throughout the next day.
- **Overmorrow correction** — reduces tonight's target if day+2 solar would overflow
  the battery (requires optional Solcast day+2 entity).
- **Solcast P10/P50 conservatism** — blend P10 pessimistic forecast into the charge
  target via a configurable slider (default 0.35, same as PALM).
- **Per-slot load history** — accumulates 48-slot (30-min) baseline load profiles over
  7 days. The charge calculation does not use the profile yet.
- **Seasonal charge bypass** — winter months charge to 100%; shoulder months apply
  the `CHARGE_SHOULDER_MIN_SOC` floor.

**Hardware protection**
- **Minimum write interval** — 5-minute per-entity cooldown prevents rapid register writes.
- **Battery throughput daily budget** — optional daily kWh cycling limit (off by default)
  with OK/High/Over budget status sensors.
- **Battery degradation cost guard** — optional `battery_cost_eur` config prevents surplus
  diversion when the export rate is below the battery wear cost per kWh.

**New services**
- `get_roi_summary` — structured ROI metrics for today/week/month/year with response_variable
- `compare_tariff` — what would this billing period have cost on a different tariff?
- `year_on_year_summary` — current month vs same month last year (requires 12+ months)
- `export_energy_data` — writes `/config/givenergy_energy_export.csv` for data backup

**New sensors (all disabled by default except House Load Today)**
- Solcast P10 entity, forecast conservatism slider
- Carbon intensity (g CO2/kWh) and Low/Medium/High status
- Pre-boost export: spare_kwh, net_gain, recommended
- ROI metrics: self_consumed_kwh_today, net_position_today, battery_life_consumed_today
- Counterfactual cost tracking: saving_vs_grid_today, net_saving_today
- Trailing 12-month: solar, import, export kWh + import cost + export earnings
- Monthly export snapshots (12-month history for year-on-year comparison)
- Battery years remaining estimate (cycles per day since tracking started, shown after 7 days)
- Battery throughput budget used / status
- Battery usable capacity estimate, energy available, charged and discharged today
- Battery state (Charging/Discharging/Full/Idle) and night survival confidence
- Average import rate: today/week/month
- Cheap import fraction: week/month
- Battery round-trip efficiency today and solar capture efficiency today
- Cheapest tariff rate and period name; on cheapest rate and on base rate
- Next cheap rate start (HH:MM), hours to cheap rate and minutes remaining in the period
- Rate saving versus the daytime rate
- Grid power direction, solar output as a percentage of inverter maximum, net solar surplus
- EV km charged today and EV cost per km (uses the new car efficiency option)
- House load today, net financial position this month
- Integration version (diagnostic) and days elapsed in the billing period

**Options flow improvements**
- Hardware settings section: update battery capacity, inverter max output and immersion
  wattage without reinstalling
- EV section: car efficiency in kWh/100 km

**Dashboard**
- Energy Today summary card on the power flow view

---

### v0.2.1

- **Remove EV battery protection** — the 50% SoC protection that stopped the Zappi and
  the cheap-rate guard that stopped it when the battery was discharging are both removed.
  The Zappi (myenergi) and GivEnergy inverter are separate systems; stopping the Zappi
  does not protect the GivEnergy battery. `ev_draining_battery`, `ev_charging_source`,
  and `ev_solar_surplus_available` remain as informational sensors. (#71, #72)
- **Year-to-date sensors** — `solar_this_year`, `export_this_year` accumulators added;
  persistent storage extended to include the `year` accumulator. (#67)
- **Dashboard updated** — EV charging source, solar surplus, and inverter temperature
  sensors wired into the dashboard. (#62)
- **Auto-init dashboard file** — `givenergy_dashboard.yaml` placeholder created on
  first setup so YAML-mode dashboards load immediately. (#59)
- **Coordinator tech debt** — `_write_floor_target` extracted; `export_rate` read
  directly from config rather than cached field. (#65)
- **555 unit tests**

### v0.2.0

**Battery & charging fixes**
- **Free battery discharge overnight** — when the integration skips overnight charging it
  now writes the minimum SoC target to GivTCP so the battery can discharge freely; previously
  the old target (e.g. 80%) stayed in GivTCP and the inverter held the battery at that level,
  importing from grid instead of discharging
- **EV battery protection raised to 50%** — daytime Zappi protection threshold raised from
  20% to 50%; preserves battery for evening/night rather than letting the car drain it during
  the day
- **EV stopped during cheap rate if battery discharges** — when a cheap rate period is active
  and the battery is discharging, the Zappi is paused; grid is cheap, the car should charge
  from grid only and not drain the battery

**Immersion heater**
- **Run-to-target on manual on** — turning on the Immersion Heater (Managed) switch (manually,
  via automation, or physical button) now runs the heater until the water reaches the configured
  target temperature, then auto-releases back to auto mode
- **10-minute cooldown between auto decisions** — prevents rapid on/off cycling caused by
  brief solar surplus fluctuations; manual on/off bypasses and resets the cooldown
- **External state change detection** — if an automation or physical button turns the immersion
  on externally, the integration activates run-to-target mode; external turn-off applies a
  cooldown before auto-divert resumes

**Dashboard**
- **Writes to file** — `get_dashboard_yaml` writes `givenergy_dashboard.yaml` directly to
  the HA config directory; no copy-pasting from a notification
- **Refresh Dashboard button** — new button entity on the device page regenerates the file
  on demand; also appears as a button card in the Controls tab
- **Current rate and period** — shown above the cost breakdown on the Today tab
- **Immersion savings** — added to the Today cost breakdown
- **Battery power** — live charge/discharge watts added to the Battery tab
- **Cheap rate floor status** — shown in the Battery charge plan card
- **Tonight's Charge Plan** — typo fixed (was "Tonights")
- **Immersion temperature sliders** — target, minimum, and restart gap now inline in
  the Controls immersion card
- **Battery SoC** — shown on the power flow card
- **HACS dependency reduced** — `vertical-stack-in-card` no longer required (replaced with
  native HA gauge card)

**Quality scale (HA Silver/Gold/Platinum)**
- **entity-unavailable** — sensors go unavailable when GivTCP stops publishing (#35)
- **reconfiguration-flow** — inverter serial, MQTT topic, and entity mappings can be changed
  without reinstalling (#36)
- **exception-translations** — `ConfigEntryNotReady` and `UpdateFailed` use translation keys
  (#36); `get_dashboard_yaml` raises `ServiceValidationError` when unconfigured (#37)
- **log-when-unavailable** — coordinator logs a warning once when GivTCP goes offline and
  logs info once on recovery (#37)
- **icon-translations** — `icons.json` with MDI icons for all entities (#38)
- **docs-examples** — `docs/automations.md` with 7 ready-to-use HA automation examples (#39)
- **docs-troubleshooting** — `docs/troubleshooting.md` covers all common failure modes (#39)
- **repair-issues** — `givtcp_entities_missing` repair issue in Settings → System → Repairs
  when entities are absent from HA; cleared on recovery (#40)
- **strict-typing** — `[tool.mypy]` added; `core/` passes mypy strict; HA layer uses
  per-module relaxation (#42)

### v0.1.5

- **Battery stats persistence** — `total_cycles` and `last_full_charge_date` now saved
  to HA Storage every 5 minutes and restored on restart; `battery_total_cycles` and
  `days_since_full_charge` no longer reset to 0/unknown after every HA restart
- **Solar forecast today fixed** — `on_charge_decision()` was never called; `solar_forecast_today`
  sensor now correctly shows today's forecast (was always 0.0), and forecast accuracy
  sensors (`forecast_accuracy_yesterday`, `forecast_accuracy_7_day_average`) now accumulate
  correctly
- **Weekly/monthly sensor state class** — 16 weekly and monthly sensors changed from
  `TOTAL_INCREASING` to `TOTAL`; prevents HA recorder warnings when float rounding causes
  micro-decreases (e.g. 126.621 < 126.685 kWh)
- **Cheap rate floor logic** — new `cheap_rate_floor_soc` config option; during cheap rate
  periods the integration tops up the battery if SoC drops below the configured floor;
  waits for the cheapest sub-window (Nightboost) rather than triggering on any cheaper period
- **Immersion temperature controls** — target temperature, minimum temperature, and restart
  gap now exposed as `RestoreNumber` dashboard sliders; values persist across HA restarts;
  removed from config flow (live-editable on dashboard)
- **EV charger discovery** — retries discovery when previously-found charger has no power
  entity (entity may appear after initial boot); logs a warning when charger is found but
  power entity is missing
- **Export rate fix** — `coordinator.export_rate` now populated each cycle from
  `build_tariff(cfg).export_rate`; was initialised to 0.0 but never written, causing
  dashboard service call to always pass 0.0
- **`_read_optional_float` proxy fix** — now uses `_get_state()` proxy instead of calling
  `hass.states.get()` directly; makes the method correctly testable and consistent with the
  rest of the coordinator
- **Sensor exception logging** — bare `except Exception` in sensor `value_fn` now logs the
  sensor key and exception instead of silently returning `None`
- **Accumulation gap logging** — engine now logs at DEBUG when an accumulation cycle is
  skipped due to a large elapsed time (probable HA restart or downtime)
- **Appliance constants extracted** — `APPLIANCE_MIN_BATTERY_SOC = 80` and
  `APPLIANCE_RATE_THRESHOLD = 1.5` added to `const.py`; `suggest_appliance_run` no longer
  uses inline magic numbers
- **Dashboard improvements** — power flow card: clipping shown as `secondary_info` template
  on solar entity; current rate shown as `secondary_info` on grid entity; immersion section
  added (apexcharts temperature history with threshold lines, tile reason card, energy chart);
  Today tab uses glance card for energy summary; Battery tab uses vertical-stack-in-card
- **`import_executor: true`** — added to manifest.json for HA 2026.7+ blocking call prevention
- **Entity registry cleanup** — `service_` prefix removed from 6 entity IDs that were
  registered with wrong device name at first install
- **Tests** — 507 passing (up from 448); `TestBatteryStatsPersistence`, `TestForecastRecording`,
  `TestWeeklyMonthlySensorStateClass`, `TestEVPowerEntityWarning` (caplog-based),
  `TestReadOptionalFloatProxy`, `TestPowerFlowTabChanges` added;
  duplicate `test_swicth.py` deleted; `test_switch.py` import path assertion corrected

### v0.1.4

- **Timezone fix** — all datetime operations now use HA's configured local timezone
  via `dt_util.as_local()`; rate periods now activate at the correct local time
  year-round (was 1 hour late in summer due to UTC comparison against local-time
  rate period boundaries)
- **Midnight reset** — now happens at local midnight rather than UTC midnight
- **`last_reset` sensor** — no longer corrupts the timezone on stored local timestamps;
  backwards-compatible with old UTC-stored values
- **Required datetime parameters** — `now`/`dt` made keyword-only required in
  `build_coordinator_data`, `calculate_overnight_charge_target`, `get_current_rate`,
  and `days_remaining_in_bill_period`; nullable fallbacks removed
- **Power flow card** — `invert_state` removed from grid entity (coordinator now
  handles sign convention; double-negation was causing Home consumption to show 0W)
- **Power flow card** — individual devices moved to `entities.individual` key
  (correct key for power-flow-card-plus v0.3.x; `individual_devices` was silently
  ignored)
- **Dashboard** — 30-day daily cost bar chart added (`statistics-graph`)
- **Dashboard** — intraday cost history line graph added (`history-graph`)
- **Tests** — 448 passing (up from 401); `TestTimezoneHandling` DST behavioural test
  added; `TestTimezoneHandling` proves night rate at local 23:30 != UTC 22:30

### v0.1.3

- **Persistence bug fixed** — `AccumulationStore.async_load()` was never called;
  energy accumulators (today, week, month, yesterday) now correctly restored from
  HA Storage on every restart
- **Week/month accumulators fixed** — `accumulate_energy` was only called on `acc`
  (today); week and month accumulators now accumulate on every coordinator cycle
- **Dead code removed** — four unused functions removed from `engine.py`
  (`_set_accumulators`, `_apply_charge_decision_overrides`, `_set_ev_charger_data`,
  duplicate `_set_immersion_decision`)
- **Cheapest rate guard** — `get_cheapest_rate()` replaced with
  `min(tariff.rate_periods, key=lambda p: p.rate)` guarded by empty-list check;
  prevents writing a zero-length charge window to GivTCP when base rate is cheaper
  than all timed periods
- **Tests** — `TestPersistence`, `TestWeekMonthFunctional`, `TestInvertedRateTariff`,
  `TestCheapestRateWindow` added with full behavioural coverage of all four fixes

### v0.1.2

- **Battery power sensor** — `sensor.battery_power` exposes live charge/discharge
  watts (positive = charging, negative = discharging) for power flow card
- **Immersion heater power sensor** — `sensor.immersion_power` returns configured
  wattage when managed switch is on, 0 otherwise; reads from integration config
  rather than a hardcoded template helper
- **GivTCP v3 grid sign fix** — GivTCP v3 uses positive=export; coordinator now
  negates on read so internal convention (positive=import) is correct; previously
  all solar export was accumulated as import, inflating costs and showing 0W house
  load on power flow card
- **EV charger auto-discovery** — power flow card generator checks for myenergi Zappi,
  Wallbox, and Ohme before falling back to integration's own EV sensor (which reads
  from GivTCP and may show 0W for independently-integrated chargers)
- **Power flow card** — battery entity corrected to use `battery_power` (watts) not
  `battery_soc` (percentage); individual devices added for car charger and immersion
- **Translations** — `battery_power` and `immersion_power` added to `strings.json`
  and `translations/en.json`

### v0.1.1

- Coordinator refactored to use `entry.runtime_data` throughout
- Tariff configuration refactored with structured rate period sections in options flow
- `TimeSelector` used for rate period start/end (was free-text)
- Comprehensive documentation added: `docs/configuration.md`, `docs/tariff.md`,
  `docs/how-it-works.md`, `docs/entities.md`, `docs/dashboard.md`,
  `docs/troubleshooting.md`, `CLAUDE.md`
- `integration_type: device` and `async_set_unique_id` for single-instance enforcement

### v0.1.0

- Initial release — full feature set as described in Current State above
- 162 unit tests, 100% coverage of pure logic modules