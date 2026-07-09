# GivEnergy Inverter Manager — Roadmap

Organised by theme and priority.

---

## Current State (v0.1.5)

### What is built and working

- **GivTCP auto-discovery** — scans HA for `sensor.givtcp_{SERIAL}_*` entities and
  pre-fills the setup form
- **Multi-brand EV charger discovery** — Zappi (myenergi), Wallbox, Ohme, Easee, OCPP
- **Zappi battery protection** — detects when the Zappi is draining the battery and
  switches it to `Stopped`; resumes `Eco+` when battery recovers and solar surplus
  is available
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
- **83 sensors** — live power/energy, cost, tariff, battery health, charge decision,
  immersion, EV, bill projection, yesterday/week/month accumulators, forecast accuracy
- **Dashboard generator** — `get_dashboard_yaml` service produces a ready-to-use
  4-tab dashboard (Power Flow, Today, Battery, Controls) including cost history graph
  and 30-day cost bar chart
- **HACS-ready** — `hacs.json`, `manifest.json`, `strings.json`, `translations/en.json`,
  custom icons
- **507 unit tests** — full coverage of all pure logic modules

---

## Near-Term (v0.2.0)

### `entity-unavailable` quality scale item

Sensors should report `unavailable` when GivTCP is not publishing data rather than
holding the last known value indefinitely. This requires tracking the age of the last
MQTT message and setting coordinator state accordingly.

**Complexity:** Low.

---

### Reconfiguration flow

Allow changing inverter serial, MQTT topic, and entity mappings after initial setup
without deleting and re-adding the integration. Required for HACS Silver quality scale.

**Complexity:** Low–Medium.

---

### `exception-translations` and `icon-translations`

Add `icons.json` and move exception strings to `strings.json` for full HA quality
scale compliance. Remaining items to reach Silver.

**Complexity:** Low.

---

### Solcast multi-array support

The integration currently accepts a single forecast entity. Homes with east and west
facing arrays benefit from separate Solcast rooftop sites. Add a second optional
forecast entity in config flow; sum both for the overnight charge decision.

**Complexity:** Low.

---

### 95% test coverage target

Several coordinator integration paths (config flow steps, options flow,
`async_setup_entry` teardown) are not covered by the current test suite. Moving to
`pytest-homeassistant-custom-component` would allow proper end-to-end integration
tests.

**Complexity:** Medium.

---

## Medium-Term (v0.3.0)

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