# GivEnergy Inverter Manager Roadmap

Planned work, ranked by MoSCoW priority. What each release shipped is in the [Changelog](#changelog).

---

## How priorities are decided

- **Must have**: the integration shows wrong numbers (against the meter, the bill or a measured baseline), makes a wrong charge decision, or loses data.
- **Should have**: measurable money or a clear usability win.
- **Could have**: useful, but a lower return or it needs more data first.
- **Nice to have**: polish or speculative.
- **Won't have for now**: decided exclusions.

Each item has a short title, what and why, the evidence, a rough value in EUR per year with a confidence (high, medium, low), and a size.

- **Sizes:** S is a day or less. M is two to four days. L is a week or more.
- **Values** come from two read-only savings reports written on 6 October 2026. The *tariff review* covers 30 days from 6 September. The *household review* covers 10 days from 26 September. Both annualise autumn data, so read the values as order of magnitude. They will be wrong in winter and summer.
- **The prize is small, the risk is bad numbers.** The tariff review found most time-of-use and solar value already captured: about EUR 167 saved in 30 days, with a controllable pool of about EUR 265 to 335 a year on top. Wrong numbers cost more trust than the pool is worth, so the Musts come first.

---

## Shipped

| Release | Theme |
|---|---|
| v0.7.0 | Clean Code limits enforced in ruff. One verified GivTCP writer, an immersion actuator, the coordinator update as named steps, the dashboard builder as a package, and golden snapshot tests. No entity id or option changed |
| v0.6.0 | One owner for the charge target override. Dry-run last skipped action kept. Countdowns correct across clock changes. The floor top-up never lowers a higher target. Configured currency in reasons and reports. Shared entity base class. CI runs on every pull request |
| v0.5.0, v0.5.1 | Battery Power positive while charging. Dashboard rebuilt as sections of tiles with six sub-views, Home Assistant 2026.2.0 or later. Night survival confidence explains itself. Device manufacturer shows `macuistin` |
| v0.4.0 | Bill reconciliation fixes (flat PSO levy, bill start day, `compare_tariff`). Per-slot load profile, forecast accuracy correction and the day-after-tomorrow forecast feed the charge target. Equivalent full cycles seeded from the BMS. Guarded inverter writes. Zappi discovery and EV cost. `last_reset` on week, month and year sensors. Config field help. Dashboard v2 with an optional strategy. Diagnostics redaction. A real Home Assistant end-to-end suite |
| v0.1.0 to v0.3.0 | First release, the forward SoC simulation, ROI and tariff services, the immersion run-to-target, HACS packaging and the first quality scale rules |

**In review:**

- After-midnight forecast read the wrong day (#184, branch `fix/forecast-day-after-midnight`). Since the charge write moved to 01:59, the decision read the day after the one it served (34.8 kWh instead of 7.1 kWh on 6 October).
- Saving sensors priced all load at the Day rate (#185, branch `fix/saving-and-ev-sensors`). `saving_vs_grid_today` read about double.
- A repair, with a one-click fix, for any other active charge slot (branch `feat/charge-slot-repair`). This is the core of S1.

They move to Shipped when merged.

**Closed after review.** M1 in the first draft, the cheap-rate floor overwriting the charge target, was already fixed. The 3 and 4 October nights ran on a version older than v0.4.0, as the stray zero-length period shows. #156 (v0.6.0) stops the floor lowering a higher target, and since v0.4.0 a rate period whose start equals its end is skipped. That stray "Night 2 00:00 to 00:00" period had made the charge window 00:00 to 00:00.

---

## Must have

Wrong numbers, wrong charge decisions or data loss. Do these first.

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **M2 Fix the saving sensors** | `saving_vs_grid_today` and `net_saving_today` price all house load at the base (Day) rate, including the EV and night load. They credit the tariff, not the solar and battery. Price each kWh at the rate it would have paid, and keep recorder history (both are off by default, and the live sensors have none) | Tariff review: 30-day total about EUR 327 against EUR 167 measured. The EV alone is about EUR 100 of the gap | Not applicable (accuracy) | M |
| **M3 Confirm EV power reads the Zappi, then fix what is left** | `ev_power`, `zappi_today` and `zappi_cost_today` read 0 for six weeks. The cause was the lookup, which needed a serial in the entity id. The Zappi here has none, and that was fixed in v0.4.0 (installed 5 October). The car has not charged since 3 October, so check `sensor.givenergy_inverter_manager_ev_charging_power` on the next session. If it still reads 0, read power from `sensor.myenergi_zappi_power_ct_internal_load` and use the Zappi's own energy counters (`green_energy_today`, `energy_used_today`, `charge_added_session`) for energy and the solar and grid cost split. `rest_of_house_load` and the baseline subtract EV power, so they keep the EV until it does | Household review: EV power weekly max 0 for six weeks against 7.1 kW sessions. `rest_of_house_load` weekly max 8,889 W against 11,060 W house load. Bill reconciliation, Oct 2026 | Not applicable (unlocks S2, S3, S5, C1) | S |
| **M4 Correct forecast bias and make the P10 blend work** | Solcast runs about 27% high. Scale the forecast by the measured actual to forecast ratio. `forecast_entity_p10` is blank, so `forecast_conservatism` (0.35) does nothing. Document how to pick the Solcast P10 attribute. The v0.4.0 accuracy correction (clamped 0.6 to 1.2) exists, but its input compared against the wrong day until #184 | Tariff review: actual was 73% of forecast over 30 days, 26 of 30 days over-forecast, mean absolute error 6.6 kWh, falling to 2.8 kWh when scaled by 0.73. Household review: median ratio 0.59 over the last 9 days | About 35 (low to medium) | M |
| **M5 Put loss, wear and the window cap into `pre_boost_export_net_gain`** | The gain ignores round-trip loss and wear, and assumes 9.04 kWh can be bought back at 0.1056 when 02:00 to 04:00 delivers at most 7.4 kWh. `pre_boost_export_recommended` says yes on that basis. Whether battery export earns the 0.195 export rate is unconfirmed | Tariff review: shown EUR 0.81, realistic about EUR 0.2 per qualifying night. About 12 of 29 nights qualify | 25 to 35 once correct (low) | S |
| **M6 Find why band import statistics read 0** | `import_kwh_cheap_today` and `import_kwh_peak_today` show a daily change of 0 on 17 of 30 days although GivTCP shows import, so a band split built from long-term statistics is wrong. Trace the accumulator and the recorder path, then add a test that fails on a zero day | Tariff review: `grid_import_today` statistics also read 0 on 6 and 7 Sep while the cost sensor shows 2.87 and 9.74 | Not applicable (accuracy) | M |
| **M7 Check `vat_rate` and raise a repair when it looks wrong** | The live entry had `vat_rate` 30 and costs were about 29% too high from 5 October. It was set to 9 on 6 October. The code default is 9 (`DEFAULT_VAT_RATE`). What is left is a repair when the configured VAT disagrees with the tariff, so it cannot drift again | Tariff review: 5 Oct cost EUR 3.85 expected against 4.97 on the sensor | Not applicable (costs +29%) | S |
| **M8 Keep stored rate periods when the options form omits them** | `_slots_to_rate_periods` in `config_flow.py` builds the list only from the `rate_period_N` sections it receives and skips any with no name. An options form submitted through the API without them replaces the tariff with an empty list, which means a flat tariff and no charge write-back. Keep the stored periods when a section is missing | Found by reading the options flow. No loss seen on the live entry | Not applicable (data loss) | S |

---

## Should have

### Savings

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **S1 Take over charge schedules** | Raise a repair when any other charge slot is active in GivTCP. Offer a one-click fix in the repair that clears the conflicting slots, so grid charging happens in Nightboost, with no new option. Slot 1 stayed 00:00 to 00:00 until 5 October, and a leftover slot 2 (00:00 to 08:00) charged at the Night rate. Charging is capped at 7.4 kWh a night in the window (3.7 kW for 2 h) | Tariff review: 114.9 kWh of grid charge landed in the Night band, 88 kWh shiftable. Household review: 9.1 of 62.1 kWh landed in 02:00 to 04:00 | 75 to 100 (medium) | M |
| **S2 Add a nightly EV top-up and an EV charge window in Nightboost** | Notify at about 21:00 to plug in, then cap each session to 02:00 to 04:00 plus a small top-up, through `select.myenergi_zappi_charge_mode` or a Zappi schedule. The gain needs a plug-in most nights. On session nights the window is already full | Household review: 176.6 kWh in 10.4 days cost EUR 27.47, re-priced EUR 20.78. Tariff review: every overnight session in 30 days already spans 02:00 to 04:00 | 115 to 235 (low to medium) | L |
| **S3 Alert when the EV charges at the Day rate** | Notify when the car draws from the grid in the Day band, so the session can move to Night. 54 kWh in 30 days: 26 kWh on 19 Sep at midday, 9 kWh on 11 Sep before 23:00, 7.5 kWh on 20 Sep after 07:00 | Tariff review: moving them to the Night rate saves EUR 9.5 per 30 days | About 115 (medium). Overlaps the low end of S2 | S |
| **S4 Schedule immersion heating into Nightboost** | Heat in 02:00 to 04:00 through the managed switch (`immersion_heater_managed`, off today), with surplus-only top-ups by day. Also covers the old predictive immersion item, which runs in Nightboost when the forecast is low. The divert rule compares solar with the import rate, but export pays 0.195, above Nightboost at 0.1056, so review the rule as part of this | Tariff review: 127 kWh in 30 days, about 60 kWh in Night and Day bands. Household review: 27.4 of 42.4 kWh in 10.4 days was not solar. Hot water timing and tank loss are unmeasured | 25 to 150 (low). Tariff review 25 to 70, household review 70 to 150 | M |
| **S5 Make the overnight charge target load-aware** | Use a rolling non-EV evening load so the battery lasts to 23:00 and does not run flat into Day-rate import. On 4 Oct SoC fell to 4% by about 18:00 and 6.5 to 6.8 kWh came in at 0.365. Solar matched the forecast times 0.65, so load caused the miss | Household review item 4 and tariff review section 3 | 35 to 65 (low to medium) | M |
| **S6 Add a standing recommendations sensor and notification** | One sensor (proposed `saving_recommendations`) lists each suggestion with EUR per month, who acts and confidence. Send a notification when a new one appears. Build it after the items it reports | Household review section 6.3 | Not applicable (delivers the others) | M |

### Accuracy and clarity

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **S7 Fix the self-sufficiency definition** | `self_sufficiency_pct` in `core/tariff.py` subtracts all solar and battery discharge from house, EV and immersion consumption, so exported solar counts as self-used. Use (self-consumed solar + battery discharge) / house load. Document it in `docs/concepts.md` and pin it with a test on a known day. Golden files change | Code review of v0.5.1 | Not applicable | S |
| **S8 Prompt for the battery cost** | `battery_cost_eur` is 0, so wear is 0 and `net_saving_today` equals `saving_vs_grid_today`. Ask for it in setup, or raise a repair. Wear per kWh delivered is cost / (19.05 x 6,000): EUR 0.035 at 4,000 and 0.048 at 5,500 | Tariff review sections 1 and 4: both sensors read 1.5643 | Not applicable (wear sets the margin per kWh) | S |
| **S9 Define or rename the "peak" import sensors** | `import_kwh_peak_*`, `import_cost_peak_*` and `peak_import_fraction_today` measure the base (Day) rate. No peak band is configured. Change the display names and docs to base-rate wording and keep the entity ids, so statistics stay intact | `docs/sensors.md`. Household review section 1 | Not applicable | S |
| **S10 Surface the rate mismatch with GivTCP** | GivTCP reports Day 0.395, Night 0.14 and export 0.20. The manager tariff has 0.365, 0.18 and 0.195. Show the difference in a repair or a diagnostic attribute. Total cost moves about 5% either way. See open question 2 | Tariff review section 1. Household review section 7 | Not applicable | S |
| **S11 Name the forecast sensor for what it holds and settle the 200 cap** | After midnight `solar_forecast_kwh_today` ("Solar forecast today") held the next day's forecast, and `yesterday_forecast_accuracy_pct` reads "capped at 200". Once #184 is merged, check the label and remove or explain the cap | Household review section 7. Tariff review section 6 | Not applicable | S |
| **S12 Redefine the immersion savings sensors** | `immersion_savings_*` read 0.23 for the month while the immersion used 127 kWh at EUR 9.16 attributed import cost. They count diverted solar kWh only, and the heater is not managed. Rename, or add a cost by band for the immersion | Tariff review section 1 | Not applicable | S |
| **S13 Guard battery round-trip efficiency** | `battery_roundtrip_efficiency_today` read 49 to 51% from a part-day figure (4.9 kWh in, 2.5 kWh out). Add a minimum throughput, or use the lifetime ratio (92.3%). The sensor is off by default | Tariff review section 1. Household review section 7 | Not applicable | S |
| **S14 Fix the year-on-year `import_cost` delta** | `_delta` reads `import_cost` from the stored snapshot, but a snapshot stores `import_cost_by_period`. The delta equals the whole current cost and `delta_pct` is null. `tests/golden_services.json` pins 47.5 for `year_on_year_full`. Fix it and regenerate that one case. Invisible until 12 billing months of snapshots exist | `services.py`, `_year_on_year` | Not applicable | S |

### Setup and delivery

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **S15 Add dated tariff changes and a stale-tariff repair** | Apply a new rate set from an effective date. Raise a repair when rates have not been reviewed for a long time | Bill reconciliation, Oct 2026: cost about 9% low after the 1 July price change | Not applicable | M |
| **S16 Finish the admin-only settings sub-view** | Settings controls move to a sub-view for admins. Read-only states stay on the main view. In progress on branch `feat/dashboard-admin-settings` | Owner request | Not applicable | M |
| **S17 Add a per-appliance power list with roles** | Discover power sensors from the Home Assistant label `device_power`. Fall back to `device_class: power` in W with `state_class: measurement`, and skip entities with no statistics. Roles: `always_on`, `schedulable_cycle`, `discretionary`, `ev`, `immersion`. Foundation for C1 to C4 | Household review: metered devices cover about 8.6 of 21.3 kWh a day of non-EV, non-immersion load | Not applicable (unlocks C1 to C4) | M |
| **S18 Require status checks on the `main` ruleset** | The ruleset has no required checks today (it has non-fast-forward, creation, pull request and code scanning rules). Require `lint`, `Tests (Python 3.13)`, `Tests (Python 3.14)`, `Home Assistant end-to-end`, `validate`, `HACS Action` and `Analyze (python)`. A settings change for the owner | `.github/workflows/`, ruleset 18528529 read on 6 Oct | Not applicable | S |
| **S19 Clear the 15 open statistics repairs** | 13 repairs from the v0.3.0 to v0.4.0 upgrade and 2 from v0.2.1 to v0.3.0. Use Developer Tools, Statistics, Fix issue on each. No code change | `docs/long-term-statistics.md` | Not applicable | S |

---

## Could have

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **C1 Add standby baseline and unmetered load sensors** | `standby_baseline_w` (rolling 4 h minimum of rest-of-house load), `standby_cost_per_year`, `metered_always_on_w` and `unmetered_load_w`. They show where the base load goes. Needs S17 and M3 | Household review: overnight floor 372 to 575 W, metered always-on about 234 W, unmetered about 530 W on average. `sensor.all_standby_power` is `unknown` | Not applicable (shows 350 to 750 of cost, not a saving) | M |
| **C2 Detect appliance cycles** | Washing machine start, run length and kWh per cycle, with a suggestion to run it in Nightboost or on sunny hours. Moving to sunny hours only pays about EUR 0.015 per kWh at these rates, so lead with Nightboost. Needs S17 | Household review: 14 starts in 14 days, 7 in the Day band, about 138 kWh a year at 0.3 to 0.5 kWh a cycle | 10 to 36 (low) | M |
| **C3 Nudge on always-on devices** | A notification first. House Comms draws about 122 W around the clock. Office Power 1 and Office Desk Right sit at 16 to 20 W outside working hours. Switching plugs off is opt-in only. Needs S17 and C1 | Household review: House Comms EUR 183 a year at 0.1718, office plugs about 233 kWh a year | 85 to 115 combined (low) | M |
| **C4 Add data-quality diagnostics** | Report a negative energy sensor (`sensor.electricity_hourly_consumption` reads -15,164 kWh), power sensors that are unavailable with no statistics, unit mismatches (`sensor.mg_mgs5_ev_charging_power` is in kW) and delta counters marked `total_increasing`. Skip these in discovery. Needs S17 | Household review section 7 | Not applicable | M |
| **C5 Build the daily review into the integration** | A sensor or notification with the day's money, anomalies and recommendations. Today a scheduled task outside the integration writes it to `~/givenergy-reports`. Needs M2, M3 and S6 | Daily review 2026-10-06 | Not applicable | L |
| **C6 Replace remaining source-grep tests** | Tests that read a source file and assert a string, for example in `test_config_flow.py`, `test_coordinator.py` and `test_switch.py`. They fail on harmless edits and pass on broken behaviour. Re-measure before quoting counts | `CLAUDE.md`, code review of v0.5.1 | Not applicable | M |
| **C7 Fix the dry-run managed switch** | In dry run, a press on the managed switch sends nothing and records nothing (`_send_manual` in `immersion_actuator.py`), while the actuator state still changes. Record it as a skipped action | Reading `immersion_actuator.py` | Not applicable | S |
| **C8 Use the service constant in `button.py`** | `button.py` calls the literal `"get_dashboard_yaml"`. Use `SERVICE_GET_DASHBOARD_YAML` from `const.py` | `button.py`, `const.py` | Not applicable | S |
| **C9 Audit the icons** | 23 sensors need a review. Most descriptions set `icon=` while `icons.json` also holds icons, and `icon-translations` is `todo` in `quality_scale.yaml` | Owner audit. Code review of v0.5.1 | Not applicable | S |
| **C10 Fix the first-setup currency and units form quirk** | Currency and units on the first-setup form behave unexpectedly. Reproduce and describe it before changing it | Owner request | Not applicable | S |
| **C11 Pay down mypy debt** | 266 errors in the Home Assistant glue. `core/` is clean. Fix them, then add a mypy job to CI and close `strict-typing` in `quality_scale.yaml` | `quality_scale.yaml` | Not applicable | L |
| **C12 Move to the planned folder layout** | `coordinator.py` becomes a `coordinator/` package. The dashboard strategy (`strategy.py`) and `frontend/` move into `dashboard/`. Touches files every open branch edits, so do it between stacks | Owner request | Not applicable | M |
| **C13 Test the Home Assistant floor version nightly** | `hacs.json` says 2026.2.0, but the end-to-end suite runs on one newer pinned release. A nightly run on the floor catches use of an API it lacks | Code review of v0.5.1 | Not applicable | S |
| **C14 Move the currency unit to an ISO 4217 code** | Monetary sensors use a symbol. Home Assistant expects `EUR`. Changing it stops recording until each statistic is repaired, so it needs a repair plan first | `docs/long-term-statistics.md` | Not applicable | M |
| **C15 Add a calibration service for supplier bills** | Match the integration's totals to a bill. powercalc `calibrate_cost` is the model | Bill reconciliation, Oct 2026 | Not applicable | M |
| **C16 Document that export reads about 2% above the meter** | The inverter-side measurement differs from the supplier meter | Bill reconciliation, Oct 2026 | Not applicable | S |
| **C17 Add a battery state of health sensor** | From the GivTCP calibrated and design capacity, plus battery temperature | External research, Oct 2026 | Not applicable | M |
| **C18 Add on and off delays and smooth the net surplus** | Hold a sustained condition before switching (evcc: enable 1 minute, disable 3 minutes). Smooth the net surplus, not only solar, and seed the average from the first reading | External research, Oct 2026 | Not applicable | M |
| **C19 Arbitrate priority between EV, immersion and battery** | Settle who gets the surplus, and who gets the Nightboost window when S1, S2 and S4 all want it. A shared supply limit belongs here (11.7 kWh an hour was seen with EV and battery together) | Household review: items 1 and 3 compete for the same window | Not applicable | M |
| **C20 Deadline heating and a pasteurisation cycle** | Reach a temperature by a set time in the cheapest window. Add a periodic pasteurisation cycle apart from the minimum temperature floor. The cycle needs the owner to confirm a target temperature | External research, Oct 2026 | Not applicable | M |
| **C21 Make the charger minimum power depend on phases** | 1,380 W is right for a single phase only | External research, Oct 2026 | Not applicable | S |
| **C22 Support Solcast multi-array** | Sum a second forecast sensor with the first. An unmerged branch, `givenergy-solcast-multi-array`, exists. A template sensor that sums the arrays works today | `REQUIREMENTS.md`, known limitations | Not applicable | M |
| **C23 Plan for GivEnergy administration** | Schedule the existing `export_energy_data` action for backups, detect and use `givenergy-local` if GivTCP is unavailable, and document migration to another inverter brand | `REQUIREMENTS.md`, non-goals | Not applicable | L |

---

## Nice to have

| Item | What and why | Evidence | EUR per year | Size |
|---|---|---|---|---|
| **N1 Charge by carbon intensity** | Carbon intensity sensors exist since v0.3.0. Use them to prefer low-carbon import and export. Cost-led today, so it needs a decision first | Existing roadmap | Not applicable | M |
| **N2 Compare tariffs live** | Compare plans on persisted per-slot data (issue 114). Needs a 30 minute import and export accumulator first. `compare_tariff` covers a billing period today | Issue 114 | Not applicable | L |
| **N3 Support multiple inverters** | Sum solar and battery SoC across GivTCP inverters, for a gateway and AIO homes | Existing roadmap | Not applicable | M |
| **N4 Make immersion weather-aware** | Use weather as well as the solar forecast when choosing between Nightboost and solar heating. Needs S4 | Owner request | Not applicable | M |
| **N5 Speak a daily summary** | A voice summary built on `today_summary` | Owner request | Not applicable | S |
| **N6 Add per-room energy cards** | Dashboard cards from the device list. Needs S17 | Owner request | Not applicable | M |
| **N7 Show appliance cost per use in notifications** | Needs C2 | Owner request | Not applicable | S |
| **N8 Track a battery health trend** | Chart state of health over time. Needs C17 | Owner request | Not applicable | S |
| **N9 Check fridge duty cycle** | Flag a rising duty cycle on `sensor.fridge_power`. The plug may carry other appliances | Household review: 53 W average, 22% duty at about 240 W, 463 kWh a year | 40 to 50 if replaced (low) | M |
| **N10 Infer occupancy and routine from load shape** | Opt-in, and always labelled as inference | Household review section 3.8 | Not applicable | M |
| **N11 Support more hardware** | Multiple EV chargers (cost per charger, priority), storage heaters (charge during Nightboost, needs a plug or CT), a second immersion element or heat pump cylinder (COP-aware cost), heat pump integration, demand response from EirGrid signals | Existing roadmap | Not applicable | L |
| **N12 Read a per-slot solar curve and day-ahead tariffs** | Use a per-period forecast attribute instead of a fixed bell curve (depends on what Solcast exposes). Dynamic day-ahead tariffs need a verified source first | Existing roadmap | Not applicable | L |
| **N13 Plan the EV by departure time** | A departure-time plan over the tariff windows, as a signal for automations (evcc planner) | External research, Oct 2026 | Not applicable | M |
| **N14 Build a charge plan timeline card** | Only if core cards cannot express it | Existing roadmap | Not applicable | M |
| **N15 Rework the EV step of the config flow** | Show discovered chargers, confirm entity mapping, ask car-specific questions, test that the mode entity is writable | Existing roadmap | Not applicable | M |
| **N16 Add translations** | `ga`, `sv` and `nb`. A community contribution | Existing roadmap | Not applicable | S |
| **N17 Tidy the engineering plumbing** | Read GivTCP's own write count when present. Remove the `strings.json` and `translations/en.json` duplication. Replace `logging.py` (about 425 lines) with a logger filter. Move fields set after the engine runs into the engine call. Add issue templates that ask for diagnostics and the GivTCP version, and decision records for the cycle definition and tariff model | Code review of v0.5.1 | Not applicable | M |

---

## Won't have for now

| Decision | Why |
|---|---|
| Companion HACS repositories (Power Flow Card, Energy History Card, Charge Plan Timeline Card, HTML Report Templates) | Wait until sensor naming is stable at v1.0 |
| An integration-owned dashboard that rewrites the user's Lovelace | It relies on internal Home Assistant APIs and overwrites user edits |
| A sidebar panel, a rebuild of power-flow-card-plus or apexcharts, a webpack or TypeScript pipeline | Too much to maintain for the gain |
| Linear programming or genetic optimisers and machine learning forecasters (EMHASS, EOS) | Too heavy for this integration |
| Copying code from Predbat (personal and non-commercial licence), PV Excess Control (AGPL-3.0), `ecodan_ctrl` (GPL-3.0) or OpenEMS (AGPL-3.0 or EPL-2.0) | Licences. Reimplement ideas only |
| Pausing or stopping the Zappi to protect the battery | Removed in v0.2.1. The two systems are separate and stopping the Zappi does not protect the battery |
| Cloud APIs | The integration is local, see the non-goals in `REQUIREMENTS.md` |

---

## Dependencies and order

1. **Merge #184 first.** M4, S11 and the forecast accuracy figures all read from it.
2. **One writer for the charge schedule.** S1 and S5 write it. Both go through `GivTCPWriter`, so the verified read-back and write counting apply.
3. **M3 before S2, S3, S5 and C1.** They need real EV power, and the baseline must exclude the EV.
4. **M2 before S6 and C5, with S8.** A recommendation or a daily review needs a trustworthy saving. S8 makes net saving include wear.
5. **M7 and S10 settle the tariff.** Do them before trusting any EUR figure on this page. M8 stops the options form wiping the tariff while you edit it.
6. **S17 before C1 to C4, N6 and N7.** The device list is the foundation. C1 comes before C3. C2 comes before N7. C17 comes before N8. S4 comes before N4.
7. **S1, S2 and S4 share the Nightboost window.** The battery draws 3.7 kW, the EV 7.4 kW and the immersion 3 kW, and 11.7 kWh an hour was seen. Do C19 or add a supply limit check before enabling more than one by default.
8. **C12 between stacks, then C11.** The layout move touches `coordinator.py`. Fix the types after the move, so each error is fixed once at its final path.
9. **S14 in its own commit.** It changes one golden case on purpose.

---

## Open questions for the owner

1. **Answered.** The bill shows 9% VAT, so `vat_rate` was set from 30 to 9 on 6 October (M7).
2. **Which rates are right?** The manager has Day 0.365 and Night 0.18. GivTCP has 0.395 and 0.14 (S10).
3. **Is a plug-in most nights realistic?** The top of the S2 range assumes it. Without it, S3 holds most of the value and S2 is not worth an L.

---

## Known limitations

| Limitation | Impact | Tracked as |
|---|---|---|
| Only one EV charger tracked for cost | Multi-EV homes show incomplete cost | N11 |
| Zappi Eco+ competes with the battery for solar | Suboptimal solar allocation. The integration never pauses the Zappi, because the two systems are separate | Won't have |
| Forecast.Solar is less accurate for east-west arrays | Charge target may be slightly off. A template sensor that sums the arrays works | C22 |
| Bill prediction assumes constant daily usage | Inaccurate early in the billing period | Improves as data builds up |
| GivTCP must be installed and running | Hard dependency. Detection is in place | C23 |
| Tariff rates are entered by hand | A supplier price change leaves costs low until the options are updated (seen after 1 July 2026) | S15 |
| Cycle count is an estimate when GivTCP publishes no BMS counter | Can differ from the battery's own counter | Counts discharge only since v0.4.0 |
| Monetary sensors use a currency symbol as the unit | Newer Home Assistant versions may reject statistics | C14 |

---

## Changelog

### v0.7.0

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

### v0.6.0

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

### v0.5.1

- **Device manufacturer** — the device page shows `macuistin` instead of naming GivEnergy.
  The device name, model and entity ids are unchanged. (#150)

### v0.5.0

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

### v0.4.0

Accuracy, battery, dashboard and quality work from the October 2026 bill reconciliation and
code review.

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

- Initial release with the core feature set: GivTCP discovery, the overnight charge target, immersion diversion and cost tracking
- 162 unit tests, 100% coverage of pure logic modules
