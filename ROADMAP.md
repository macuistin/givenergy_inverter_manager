# GivEnergy Inverter Manager — Roadmap

Organised by theme and priority.

---

## Current State (v0.2.1)

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
- **94 sensors** — includes all new inverter, EV, and solar opportunity sensors
- **Dashboard generator** — 4-tab dashboard; live cost rate on grid node; new sensors in
  Battery Health (inverter temp) and Controls EV (charging source, solar surplus)
- **HACS-ready** — `hacs.json`, `manifest.json`, `strings.json`, `translations/en.json`,
  `icons.json` with MDI icons for all entities
- **Repair issues** — `givtcp_entities_missing` repair issue surfaces in Settings → System
  → Repairs when configured GivTCP entities are absent from HA
- **Automation examples** — `docs/automations.md` with 10 ready-to-use HA automation
  examples including Zappi Eco+ and inverter derating alert
- **555 unit tests**

---

## Near-Term (v0.2.x) — remaining

### Register write rate-limiting and hardware protection

GivEnergy inverters have ~1 million total register write capacity. Aggressive
automation can exhaust this in under two years. The current write helpers do a
single write + read-back; they need three additional safeguards:

1. **Read-before-write** — skip the write if the register already holds the target value
2. **Retry logic** — retry up to 3 times with a 2-second sleep when GivTCP does not
   acknowledge the write (currently just logs a warning and moves on)
3. **Minimum write interval** — do not re-write the same entity more than once per 5 minutes
4. **Write counter sensor** — expose `total_register_writes` as a diagnostic sensor;
   log a warning at 500,000 (halfway through lifetime)

Research source: Predbat `inverter.py` `write_and_poll_value` pattern;
GivEnergy community flash memory degradation discussions.

**Complexity:** Low — contained within coordinator write helpers.

---

### EMA solar smoothing + dual-budget surplus diversion

The current immersion and EV diversion logic uses a single instantaneous surplus
reading. Two improvements from PV-Excess-Control and solar_optimizer:

1. **EMA smoothing** — replace `solar_power_w` with `0.5 × prev + 0.5 × current`
   in the engine accumulation cycle. Prevents chasing transient cloud gaps.
2. **Dual avg/instant budget** — maintain both a ring-buffer average and the
   instantaneous reading. The allocation budget is `min(avg, instant)`: reacts
   quickly to real drops but does not ramp past what the average sustains.
3. **Sensor unavailable safety gate** — if solar or grid readings are unavailable
   or NaN, hold the current device state rather than making decisions on bad data.

Research source: InventoCasa/PV-Excess-Control `dual_budget` model;
jmcollin78/solar_optimizer EMA pattern.

**Complexity:** Low — changes in `engine.py` (smoothing) and `rules.py` (budget logic).

---

### EV charger minimum power guard (1380W)

OCPP EV chargers have a minimum operating current (typically 6A single-phase =
1,380W). If the allocated surplus is below this, do not attempt to start or
maintain the charger — it will simply refuse the command. Without this guard,
the integration issues start commands that are silently ignored, and the charger
oscillates between starting and stopping as surplus fluctuates near the threshold.

Research source: hsem (woopstar) `charger_min_power_w` parameter.

**Complexity:** XS — one threshold check in `decide_ev_charger_action` in `rules.py`.

---

### 95% test coverage target

Config flow steps and options flow are not covered by the current test suite. Moving
to `pytest-homeassistant-custom-component` would allow proper end-to-end integration
tests covering the full HA lifecycle.

**Complexity:** Large.

---

### Monthly/annual export volume tracking

Track export kWh per calendar month and rolling 12-month total. Surface an alert
when export volume justifies renegotiating the CEG rate with the supplier.
Requires persistent storage for 12 monthly snapshots.

**Complexity:** Medium — new storage layer needed.

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

The test suite uses manual HA stubs in `conftest.py`. Migrating to
`pytest-homeassistant-custom-component` would allow proper end-to-end testing of
the config flow, coordinator setup/teardown, and entity lifecycle.

---

## Known Limitations

| Limitation | Impact | Status |
|---|---|---|
| Only one EV charger tracked for cost | Multi-EV homes show incomplete cost | Planned v0.3.0 |
| Zappi Eco+ competes with battery for solar | Suboptimal solar allocation | Mitigated by pause/resume; full resolution needs real-time power sharing |
| Forecast.Solar less accurate for east-west arrays | Charge target may be slightly off | Solcast multi-array planned v0.2.0 |
| Bill prediction assumes constant daily usage | Inaccurate early in billing period | Improves over time as more data is collected |
| GivTCP must be installed and running | Hard dependency | Documented; detection in place; `givenergy-local` fallback planned v1.0 |

---

## Changelog

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