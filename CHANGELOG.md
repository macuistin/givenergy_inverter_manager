# Changelog

What each release changed, newest first. Planned work is in [ROADMAP.md](ROADMAP.md).

## Unreleased

Stops an EV charge reading as a night shortfall, corrects the EV and immersion cost when the grid
also charges the battery, and adds an alert for EV charging at the base rate.

**Features**
- Repair "EV is charging at the base rate". When the car draws from the grid in the base-rate
  band for 5 minutes and the tariff has a cheaper timed band, the repair names the power, the
  rate and when the next cheaper band starts. It is raised once, clears when the session ends or
  the rate drops, and never appears for a flat tariff or an install with no charger. The
  integration does not stop or pause the charger.

**Fixes**
- Night survival and the overnight charge target no longer count an EV charge as house load. A
  car charging overnight used to push Estimated SoC at Sunrise to the minimum, give a false
  "Battery may run low" status and Critical confidence, and send the charge target to the cap.
  The car's energy is now left out of the average daily load. The 10 point buffer for a
  plugged-in car is unchanged.
- Estimated SoC at Sunrise no longer jumps at midnight, at 08:00 or when solar fades. It follows
  the calculated estimate at no more than the pace the inverter can charge or discharge the
  battery (inverter maximum output over battery capacity). The Night Survival Status and
  Confidence sensors and the charge plan still read the calculated figure.
- EV Charging Cost Today and Immersion Cost Today no longer include grid energy that went into
  the battery. They take their share only of the import that fed the load, and House Cost Today
  keeps the rest.
- Inverter Temperature and its status read GivTCP's `sensor.givtcp_<serial>_invertor_temperature`
  when no entity was stored at setup. The temperature dashboard rows show once that entity
  exists.

**Docs**
- The cost sensors are documented as including the supplier discount and VAT, and not the standing
  charge or the PSO levy.

## v0.13.0

Shows how the forecast accuracy correction is doing and starts it from recorded history. Adds
dated rate changes and three repairs. Fixes a year-on-year cost delta and two misleading
readings, and renames the base-rate import sensors.

**Features**
- **Overnight Charge Reason** (`overnight_charge_reason`) has new attributes: `accuracy_status`
  (for example `Waiting for data: 3 of 5 days` or `Applied: x0.80 from 7 usable days`),
  `accuracy_applied`, `accuracy_measured_factor` (the median actual to forecast ratio so far),
  `accuracy_applied_factor` (that ratio after the 0.6 to 1.2 limit, empty until 5 usable days),
  `accuracy_usable_days`, `accuracy_days_needed` and `accuracy_days_stored`. The state of the
  sensor and the text of the charge reason are unchanged.
- The forecast accuracy history is seeded from the Home Assistant recorder. On a new install, or
  when no history is stored, the integration reads the last 14 days of the tomorrow forecast
  sensor and the GivTCP daily solar total in the background, so the correction can apply from the
  first night instead of after five. With the default 10 days of recorder history that gives
  about 9 days. Seeded days count as not clipped, a stored history is never replaced, and any
  recorder problem is ignored. The first refresh after setup still reads `Waiting for data`. The
  next one shows the applied factor. `recorder` is now an `after_dependency`.
- Dated rate changes. A new Dated rate change section in Configure lets you enter the new base
  rate, timed rates and export rate with the date they start. The current rates stay in force
  until then, costs already recorded are not recalculated, and the cheap window timing follows
  the change without a reload. A date in the past is rejected. The standing charge, levy, VAT and
  discount still apply when you save. See [Tariff](docs/tariff.md).
- A repair appears when the tariff has not been saved changed, reconfigured or confirmed for 365
  days. The first run records today's date, so an upgrade never raises it straight away. Confirm
  the rates in the repair to clear it.
- A repair asks for the battery cost when it is still 0 after seven days of battery tracking.
  Without a cost, battery wear is 0 and Net Saving Today equals Saving vs Grid Today. The repair
  saves the value without changing any other saved option. Ignore it to keep wear at 0.
- A repair shows the GivTCP day, night or export rate next to the tariff entered here when they
  differ by more than 2%. It needs no setup, appears only when GivTCP's rate sensors are
  readable, and can be ignored. The rates entered here still decide every cost.

**Changes**
- The sensors that count import at the base rate are renamed from "peak rate" to "base rate":
  Import at base rate (today, yesterday, this week, this month), Import cost at base rate and Base
  rate import fraction. Keys and unique ids are unchanged, so history carries on. Existing
  installs keep their entity ids, and new installs get ids from the new names. See "Renamed
  sensors" in [Sensors](docs/sensors.md).
- Forecast accuracy yesterday and its 7-day average are no longer capped at 200. A day that beats
  the forecast by more than double now shows its real figure. A stored 200 stays until it leaves
  the 7-day window.

**Fixes**
- Year-on-year comparison: `delta.import_cost` and `delta_pct.import_cost` in
  `year_on_year_summary` now compare against last year's import cost. They equalled the whole
  current cost, with a null percentage.
- Battery Round-trip Efficiency Today (off by default) is unknown until at least 2 kWh has gone
  both into and out of the battery today. It read far too low early in the day.
- Pressing the managed immersion switch in dry run is recorded as a skipped action (Last Skipped
  Action). It no longer ends or starts a manual run on the next cycle.

**Upgrading**
- Nothing to do by hand. The first start after the upgrade records today's date as the tariff
  review date, so the stale tariff repair cannot appear for 365 days.
- You may see one or two new repairs. Battery cost not set appears after seven days of battery
  tracking while the cost is 0. GivTCP rates differ from the tariff appears if GivTCP holds
  different rates. Both can be ignored.
- Existing installs keep the entity ids of the renamed base-rate import sensors.

## v0.12.0

Four more sensors are enabled by default, the Now strip has one Cheap from tile, the Immersion
chart shows when the heater was on, and the reports use the forecast service's own figure.
Generate the dashboard file again to get the dashboard changes.

**Changes**
- **Saving vs Grid Today** (`saving_vs_grid_today`) and **Net Saving Today (inc. battery wear)**
  (`net_saving_today`) are enabled by default. Home Assistant now records their history, so a
  saving over time can be charted.
- **Battery Discharged Today** (`battery_discharge_kwh_today`) is enabled by default. The Where
  today's energy came from card on the Today tab splits solar and battery on a fresh install,
  where it showed them as one figure.
- **Next Cheap Rate Start** (`next_cheap_rate_start`) is enabled by default, so the Cheap from
  tile of the Now section shows on a fresh install. Hours to Cheap Rate stays disabled.
- A fresh install generates a dashboard with these figures in it. Existing dashboards are
  unchanged until you generate the file again.
- The Now strip on the Power Flow tab has one Cheap from tile in place of Cheap from and Cheap in.
  It reads `23:00 (in 8 h 56 min)` before a cheap period, and `Now (ends in 5 h 30 min)` during
  one. The end is where the whole run of periods cheaper than the base rate stops, so a Nightboost
  period inside Night does not cut it short.
  The tile is full width and shows the new `summary` attribute of Next Cheap Rate Start. The state
  of that sensor is unchanged, and so is the Hours to Cheap Rate sensor, which no longer has a tile.
  A stored dashboard picks this up when you regenerate it.
- The heater's power is a fixed number, so the Heater power chart is gone. The water temperature
  chart shades the times the heater was on instead, in a pale red band. With a switch and no
  temperature sensor, a small Heater on or off chart shows the same band. The Today tiles for
  energy, cost and saved by solar stay.
- The immersion charts no longer set a stroke curve or width for the whole chart. Each series
  sets its own, so the band steps between on and off without ramps, and draws no line when the
  heater is off.
- Without apexcharts-card, the built-in history graph adds the heater's power as a line. It
  cannot shade the band. The hourly immersion energy graph is removed with the Heater power
  section.

**Fixes**
- Today's energy summary report now compares solar generated today with the provider's own
  forecast for the day, the figure the dashboard's Forecast and % of forecast tiles use. Its
  Solar row read "Forecast: X kWh (N%)" from the charge plan's forecast, which is blended toward
  the pessimistic estimate and scaled by the accuracy correction, so the report and the
  dashboard disagreed. The row shows no forecast until a provider forecast has been seen at
  midnight, where it used to fall back to the plan's figure. The percentage is no longer
  capped at 200%.
- Tonight's charge plan report labels its forecast as the plan's: the row reads "Plan forecast"
  and the sensor state reads "Skip charge · Plan forecast X kWh · SoC N%". The week summary and
  its Yesterday section carry no forecast of their own, and their accuracy rows already measure
  against the provider's forecast.

**Upgrading**
- Home Assistant applies an enabled default only when it creates an entity. On the first start
  after the upgrade, setup enables these four sensors where the integration had disabled them,
  so there is nothing to do by hand. A sensor you disabled yourself stays disabled, and setup
  does not touch it on later starts. History starts from that first start.
- Home Assistant reloads the integration once, about 30 seconds after those sensors are enabled.
  It does this once, on the first start after the upgrade.
- Generate the dashboard again to get the Cheap from tile and the solar and battery split.

## v0.11.0

Self-sufficiency no longer reads 0% on the morning after a cheap overnight charge. The dashboard
says in plain words where the day's energy came from, and solar is compared with the forecast
service's own figure. Stored data moves to version 4 on first start, with no action needed.

**Fixes**
- Self-sufficiency counts grid energy that went into the battery separately. It read 0% when
  the import was larger than the house load, because the energy that charged the battery counted
  as grid supply. It now answers "how much of the house load did the grid not have to supply at
  the time": `1 - (import - grid to battery) / house load`. A day with 12.1 kWh imported, 7.5 kWh
  of it into the battery and an 11.3 kWh load reads 59%, not 0%. The week, month and yesterday
  sensors use the same figure, and so do the reports and the ROI and monthly comparison actions.
  Battery discharge of energy that came from the grid counts as supplied from storage. EV and
  immersion energy bought from the grid still counts as grid, because the house load includes
  both.
- The figure comes from GivTCP's `sensor.givtcp_<serial>_ac_charge_energy_today_kwh`, found from
  the inverter serial like the other daily counters, so there is nothing to set up. Without that
  counter (older firmware, or a counter that is not GivTCP's) all import counts as grid, as
  before. The `basis` attribute says which.
- Week, month and year figures start from the day of the upgrade. Earlier days have no
  grid-to-battery figure, so a period that began before it reads lower until it ends.

**Features**
- The four Self-sufficiency sensors (today, yesterday, this week, this month) have the
  attributes `house_load_kwh`, `from_grid_kwh`, `grid_to_battery_kwh`,
  `from_solar_and_battery_kwh` and `basis` (`ac_charge_counter` or `import_only`), so the
  percentage can be checked by hand. See [Concepts](docs/concepts.md#self-sufficiency-solar-share-and-self-consumption).
- Grid to Battery Today sensor: the part of Grid Import Today that charged the battery. A daily
  energy total with long-term statistics. Unavailable while the GivTCP counter is missing.
- The Energy today section of the Power Flow tab has a Self-sufficient tile, so the share of the
  day's use that did not come from the grid is on the first screen.
- The Today tab has a Where today's energy came from group. It says in plain words what the
  house used (solar, battery and grid, in kWh), what came in from the grid (the part the house
  used and the part that went into the battery) and what self-sufficiency means. A line for the
  EV and one for the immersion show only while that device exists, and follow a device added or
  removed later with no new file. The card reads the Self Sufficiency sensor's attributes
  `house_load_kwh`, `from_grid_kwh`, `grid_to_battery_kwh` and `basis`, and uses the House Load
  Today and Grid Import Today totals where one is missing. Solar and battery show as one figure
  until the Battery Discharged Today sensor, which is disabled by default, is enabled. Generate
  the dashboard again to get the group and the tiles. See [Dashboard](docs/dashboard.md).
- New sensor **Solar forecast today (provider)** (`solar_forecast_raw_today`): the forecast
  service's own figure for today, as it stood just before midnight. It is empty when none was
  seen then, such as on the first day of a new install.
- The **Energy today** section of the dashboard gains Forecast and % of forecast tiles when a
  forecast sensor is set. The Solar and forecast sub-view shows Forecast, % of forecast, Plan forecast
  (the charge plan's figure) and Yesterday (accuracy).

**Changes**
- **Solar vs provider forecast** (`solar_actual_vs_forecast_pct`) now compares solar generated
  today with the provider's forecast for today. It compared with the charge plan's forecast,
  which is blended toward the pessimistic estimate and scaled by the accuracy correction, so it
  read higher than the day deserved. It is empty without a provider forecast, where it used to
  fall back to the seasonal estimate. Its entity ID on an existing install is unchanged.
- **Solar forecast today** (`solar_forecast_kwh_today`) is renamed **Solar forecast today (charge
  plan)** to say what it holds. Its value is unchanged and so is its entity ID on an existing
  install. A new install gets entity IDs from the new names.

## v0.10.0

Sizes the overnight charge window to the plan, lets the immersion devices be added later,
and fixes forecast accuracy. Stored data moves to version 3 on first start, with no action needed.

The EV charger, the immersion switch and the immersion temperature sensor are optional, and
an install can add or remove any of them at any time. Entities and the dashboard now follow.

**Features**
- The immersion switch and water temperature sensor can be added, changed or cleared under
  Configure, Immersion heater, at any time. Saving reloads the integration, so there is no
  restart and no reinstall. The Immersion Heater (Managed) switch and the Immersion dashboard
  view appear or disappear to match. The element power moved from the Hardware section to the
  new section. The target and minimum temperatures stay with their number entities.
- The **GivTCP Register Write Count** sensor has a `recent_writes` attribute: the last 20 writes
  the integration made to the charge target, the charge window and the charge switches, each with
  its time, entity, value and reason. A change to the charge target, window start or window end
  that the integration did not make is added as `external`, with the Home Assistant `user_id` and
  `parent_id` when there are any, and one INFO log line. Nothing is reverted and no option is
  added. The log is saved with the other stored data.
- The charge window is sized to the plan. The window start is still the cheapest rate period.
  The end moves later when the plan needs more time than that period has, up to the end of the
  run of rate periods cheaper than the base rate that follows it. The time needed is the deficit
  from the current SoC to the target, times the battery capacity, divided by the GivTCP battery
  charge rate (`number..._battery_charge_rate`), plus a 15% margin, rounded up to 5 minutes. If
  the plan fits the cheapest period, or the charge rate cannot be read, the window is unchanged.
  The inverter stops at the target, so the cheapest hours still come first. Only slot 1 is
  written.
- An Overnight Charge Window sensor shows the window to be written, with attributes for the
  start, end, whether it was extended, the energy it should deliver and the expected finish.
  Dry run shows the extended window in the "would write" text.
- The sensors, numbers and switches that need an EV charger or an immersion are created only
  while the device exists. Before, an install without them held 11 EV sensors (6 of them never
  available), 8 immersion sensors that always read 0, 3 temperature numbers and the Auto
  Immersion Divert switch. Setup removes the registry entries of a device that is gone. The
  entities of a charger discovery has not found yet are kept while Home Assistant is starting,
  and removed by the next reload if no charger shows. See [Sensors](docs/sensors.md).
- A device added later brings its entities with it. An EV charger's appear when discovery first
  finds it, with no restart. The immersion entities appear when the options set the immersion
  switch or sensor, which reloads the integration as it always did.
- The temperature controls (Target, Minimum, Restart gap) exist only with an immersion switch
  and a temperature sensor together, as they act on nothing without both.
- Immersion Water Temperature sensor. It mirrors the immersion temperature sensor you set, and
  exists only with one. The dashboard charts it, so a stored dashboard has a stable entity for
  a sensor that is added later.
- The generated dashboard is correct for every combination of the three devices. A switch with
  no sensor has an Immersion view with no temperature chart and no Target, Minimum or Restart
  gap tiles. A sensor with no switch shows the water temperature, with no heater power chart,
  no reason text and no tiles for a heater. No device means no Devices heading and no empty
  link.
- Cards for a device carry a Lovelace visibility condition, so a file, or a dashboard pasted
  into the raw editor, shows the cards of a device the moment it exists and hides them when it
  goes, with no new file. The file points those cards at the entity IDs the device's entities
  will get. The power flow card and the cost chart are built once for each combination of
  devices.
- The Immersion and EV charger views are always in the file, with their sections hidden until
  the device exists.
- The dashboard strategy is unchanged and is still the one dashboard that is always current.
  See [Dashboard](docs/dashboard.md#devices-you-add-or-remove-later).

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
- The write count and the write log are queued for saving as soon as a write is sent. They used
  to wait for the next periodic save, so a crash soon after a write could lose it.
- The Recommended Overnight Charge Target sensor no longer jitters. The calculated target moves
  by several points between cycles in the small hours, so the sensor and its reason text
  changed dozens of times overnight. The sensors now hold their value
  until the calculated target is 5 points or more away, or the plan changes between charging and
  skipping. The value written to the inverter at the start of the charge window always comes from
  the latest calculation, never from the held value. Manual overrides and the configured cap show
  at once.

**Docs**
- The window sizing is described in Concepts and the charge rate entity in Configuration. The
  roadmap item for a second charge slot is removed, and a lower-priority item for tariffs with no
  cheaper period after the cheapest is added.

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
