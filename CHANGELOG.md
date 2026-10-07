# Changelog

What each release changed, newest first. Planned work is in [ROADMAP.md](ROADMAP.md).

## Unreleased

**Features**
- The immersion switch and water temperature sensor can be added, changed or cleared under
  Configure, Immersion heater, at any time. Saving reloads the integration, so there is no
  restart and no reinstall. The Immersion Heater (Managed) switch and the Immersion dashboard
  view appear or disappear to match. The element power moved from the Hardware section to the
  new section. The target and minimum temperatures stay with their number entities.

**Fixes**
- A switch or sensor saved in the options is now used. The managed switch and the heater
  controller read the setup data only, so an immersion switch set after setup was ignored.
- Clearing the forecast section's entities no longer happens when a submission leaves the
  section out.
- A manual or external immersion turn-on with no readable water temperature no longer heats
  for ever. With no temperature sensor set, or one that is unavailable, the run lasts 5
  minutes (the existing sensor outage hold limit) and then automatic control resumes.
- EV charger discovery repeats every 5 minutes until the power, session and charge mode
  entities are all found, not only the power entity. A charger found before its integration
  finished loading is completed with no reload.
- With no immersion switch set, Immersion Divert Reason reads `No immersion switch configured`
  and the divert decision stays off. It used to say the heater was diverting or heating.
- Missed Solar Today counts export only once an immersion switch is set or an EV charger is
  found. With neither, there is nothing that could have used the export, and the sensor stayed
  inflated.
- The today and week reports leave out the immersion saving lines when there is no immersion
  switch. They showed a permanent zero.
- EV Solar Surplus is unavailable until an EV charger is found, like the other EV sensors.
- Forecast accuracy yesterday and its 7-day average divide actual solar by the forecast for that
  day. They used the first forecast the charge calculation saw, which could be blended toward
  the P10 or belong to another day, so the figure read far too low (19% on a day the forecast
  provider had forecast 7.54 kWh and the site made 6.64 kWh, about 88%). A day with no
  remembered forecast, or with no data because Home Assistant was down, is skipped. On upgrade
  the stored history is rebuilt from the daily forecast and solar pairs the integration already
  keeps, up to the last 7 days, so the sensors show corrected values straight away. With no
  pairs stored they read 0 until the next midnight. The Solar forecast today sensor still shows
  the first forecast value the charge calculation used.

## v0.9.0

Removes three disabled sensors. No option name changes.

**Removed**
- The `pre_boost_export_recommended`, `pre_boost_export_kwh` and `pre_boost_export_net_gain`
  sensors. They advised exporting stored energy before the cheap charge, and their gain figure
  ignored round-trip loss and wear. All three were disabled by default. Setup removes their
  registry entries. A dashboard card or automation that still uses one shows unavailable until
  you remove the reference. (#205)

**Fixes**
- An EV charger counts as active only while it draws power. A Zappi keeps a Boosting status
  while its plug status reads Waiting for EV, so a car that was plugged in but not charging
  showed as boosting and, with the battery discharging to the house, as draining the battery.
  (#204)
- The Solcast P10 forecast is read from the `estimate10` attribute of the forecast sensor, so
  forecast conservatism works with no setup. A P10 sensor chosen in the options still wins.
  With conservatism above 0 and no P10 available, the charge reason says so. With Solcast and
  the default conservatism of 0.35, the forecast behind the charge target is now blended toward
  the P10, which lowers it. Set conservatism to 0 for the plain forecast. (#208)

**Docs**
- The forecast accuracy correction and the P10 blend are explained, and so are days where a
  sensor's daily change reads 0, which came from a defect fixed in v0.3.0. (#208, #206)

## v0.8.2

Small release. No entity id or option name changes.

**New**
- Solar share sensors for today, yesterday, this week and this month, and a Solar share bar in
  the Today tab's Solar section. Solar share is the share of the house's consumption met by
  solar kept on site. It ignores grid import, so it still shows what solar did on days when
  the battery charges from the grid. (#199)

**Fixes**
- Restarting Home Assistant no longer sometimes logs "Unable to remove unknown job listener"
  from the integration's storage. The integration now queues its shutdown write with the
  store, which writes at the final-write stage. (#198)

## v0.8.1

Small fixes. No entity id or option name changes.

**Fixes**
- Self-sufficiency read 100% on days with grid import. It is now one minus import over house
  load, clamped to 0 to 100%. Energy the battery took from the grid counts as import, so
  charging from the grid lowers the figure on the day it is bought. (#194)
- Saving the options with only the fields that changed no longer clears the timed rate
  periods. The options form in the UI was not affected. (#195)

## v0.8.0

Savings and correctness release. No entity id or option name changes. The Controls tab is now a
Settings sub-view, so a bookmarked `/controls` URL becomes `/settings`.

**Fixes**
- After midnight the overnight charge decision read the forecast for the day after the one it
  was charging for, because the forecast sensor moves on a day at midnight. It now reads the
  forecast remembered before midnight, with its P10, until 08:00. (#184)
- `saving_vs_grid_today` and `net_saving_today` priced all load at the day rate, so they read
  about double. Each step of load is now priced at the grid rate in force when it ran. (#185)

**New**
- A repair, with a one-click fix, when a charge slot other than the one the integration writes
  has a window set. A leftover slot charged the battery at a dearer rate than the
  cheapest period. (#187)
- The dashboard Settings sub-view, opened by a button in the Now heading, is shown to
  administrators only. The settings stay visible as read-only tiles for everyone. This is a
  display control, not security. (#188)
- The roadmap ranks planned work as Must, Should, Could and Nice. (#189)

## v0.7.0

Code quality release. Nothing in it changes entity ids or option names.

**Behaviour**
- Charge and register writes to GivTCP go through one writer that holds a lock, sets the
  value, reads it back and retries, so two writes can no longer interleave. (#169)
- Immersion diversion is driven by the coordinator and no longer depends on the immersion
  switch entity being enabled. EV and immersion actions wait for the service call to
  finish. (#174, #177)
- Appliance suggestions show your configured currency symbol. Verbose cycle log lines are
  only built when verbose logging is on. (#179)

**Clean-up**
- Clean Code limits (function length, complexity, argument count, boolean flags) are
  enforced in ruff. Existing offenders went from 60 to 3. (#165)
- `dashboard.py` is now `services.py`, the dashboard builder is a package, sensor
  descriptions are split by theme and the coordinator update cycle is a set of named
  steps. (#171, #172, #177, #178)
- Golden snapshot tests pin the config flow forms, the dashboard, the services, the
  coordinator snapshot and the reports.

## v0.6.0

Bug fixes from the architecture review, the dead-code and typing clean-up, and a shared
entity base class.

**Fixes**
- The charge target override has one source of truth. The switch turns it on, the number
  sets the value, and both survive a restart. (#154)
- "Last Skipped Action (Dry Run)" keeps its value instead of resetting within 30 seconds.
  (#152)
- Countdowns and elapsed-time sums are correct across a clock change. (#153)
- The cheap-rate floor top-up never lowers a charge target that is already set higher.
  (#156)
- Reasons, reports and form units use your configured currency instead of a fixed euro.
  (#159)

**Clean-up**
- A shared entity base class and a typed config entry. Dead code and unused constants are
  removed, and `core/` passes mypy. (#158, #163)
- Tests run from any directory, and duplicate and source-text tests are removed. (#157)
- CI runs on every pull request whatever its base, with a separate lint job, caching,
  nightly runs and Dependabot. (#161, #162)

## v0.5.1

- **Device manufacturer** — the device page shows `macuistin` instead of naming GivEnergy.
  The device name, model and entity ids are unchanged. (#150)

## v0.5.0

Upgrade notes: [docs/upgrade-v0.5.0.md](docs/upgrade-v0.5.0.md).

**Breaking**
- **Battery Power changed sign** — the sensor is now positive while charging. It used to copy
  GivTCP's raw sign. Check any automation, template or card that reads it. (#141)
- **Home Assistant 2026.2.0 or later** is required for the new dashboard layout.
- **Regenerate the dashboard** and paste it over the old copy.

**Fixes**
- Battery charged and discharged energy, round-trip efficiency and self-sufficiency were
  wrong because the battery power sign was inverted. The managed immersion switch toggling
  came from the same cause. (#141)
- Night survival and the overnight charge plan use the same window, and the plan no longer
  skips a night that survival calls Critical. (#144)
- A missing Zappi power entity is logged once, not every five minutes. (#143)

**Improvements**
- Dashboard rebuilt as sections of tiles with six sub-views. (#142)
- Night Survival Confidence explains its level in its attributes. (#146)
- Docs explain the state class repairs after an upgrade. (#147)

## v0.4.0

Accuracy, battery, dashboard and quality work from a bill reconciliation and code
review.

**Control and charging**
- Per-slot load profile, forecast accuracy correction and the day-after-tomorrow forecast
  feed the charge target. (#131)
- Zappi discovery works when the myenergi entity ids have no serial, and EV cost is
  calculated. (#129)
- Immersion control no longer flaps, the hold during a GivTCP dropout is bounded, and the
  EV thresholds are one. (#130)
- Equivalent full cycles seeded from the BMS, write errors handled, charge targets clamped
  to 4 to 100%, write count saved. (#134)

**Tariff and statistics**
- Bill sensors, flat PSO levy, billing period days, bill start day from options, rate
  period validation and `compare_tariff` corrected. (#132)
- `last_reset` for week, month and year sensors, year totals saved, accumulators stored
  durably. (#133)

**Configuration and dashboard**
- Every config field has a label and help, sliders no longer reload the entry, and
  reconfigure takes effect. (#135)
- Dashboard v2: Now strip, Bill view, built-in fallbacks and an optional strategy. (#138)
- Diagnostics redaction, repair links, services registered once and a real Home Assistant
  end-to-end suite in CI. (#136)

Known issues at release: battery charged and discharged energy could read swapped (fixed in
v0.5.0), and a missing Zappi power entity was logged every 5 minutes (fixed in v0.5.0).

## v0.3.0

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

## v0.2.1

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

## v0.2.0

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

## v0.1.5

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
  waits for the cheapest sub-window rather than triggering on any cheaper period
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

## v0.1.4

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

## v0.1.3

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

## v0.1.2

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

## v0.1.1

- Coordinator refactored to use `entry.runtime_data` throughout
- Tariff configuration refactored with structured rate period sections in options flow
- `TimeSelector` used for rate period start/end (was free-text)
- Comprehensive documentation added: `docs/configuration.md`, `docs/tariff.md`,
  `docs/how-it-works.md`, `docs/entities.md`, `docs/dashboard.md`,
  `docs/troubleshooting.md`, `CLAUDE.md`
- `integration_type: device` and `async_set_unique_id` for single-instance enforcement

## v0.1.0

- Initial release with the core feature set: GivTCP discovery, the overnight charge target, immersion diversion and cost tracking
- 162 unit tests, 100% coverage of pure logic modules
