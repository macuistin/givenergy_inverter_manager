# GivEnergy Inverter Manager Roadmap

Planned work, ranked by MoSCoW priority. What each release shipped is in the [changelog](CHANGELOG.md).

---

## How priorities are decided

- **Must have**: the integration shows wrong numbers (against the meter, the bill or a measured baseline), makes a wrong charge decision, or loses data.
- **Should have**: measurable money or a clear usability win.
- **Could have**: useful, but a lower return or it needs more data first.
- **Nice to have**: polish or speculative.
- **Won't have for now**: decided exclusions.

Items are listed in the order to do them. Within a bucket the first row is the next one to pick up.

Each item has a short title, what and why, the evidence, an indicative value per year with a confidence (high, medium, low), and a size.

- **Sizes:** S is a day or less. M is two to four days. L is a week or more.
- **Ids** are stable and never reused, so gaps in the numbering are expected.
- **Values** are indicative, from one install. They come from a few weeks of autumn data, rounded to a range and annualised, in that install's currency. Read them as order of magnitude. They change with your tariff, your house, how much you charge an EV and the season.
- **The prize is small, the risk is bad numbers.** On the install measured, the existing logic already captured most time-of-use and solar value. The controllable pool on top was small. Wrong numbers cost more trust than that pool is worth, so the Musts come first.

---

## Shipped

What each release shipped is in the [changelog](CHANGELOG.md).

---

## Must have

Wrong numbers, wrong charge decisions or data loss. Do these first.

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|

---

## Should have

### Savings

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S5 Make the overnight charge target load-aware** | Use a rolling non-EV evening load so the battery lasts until the cheap window and does not run flat into base-rate import. When solar matches the forecast but the battery still runs flat, load caused the miss | One install: on one evening the battery ran flat several hours before the cheap window and about 7 kWh came in at the base rate | 35 to 65 (low to medium) | M |
| **S4 Refine scheduled immersion heating** | Scheduled heating in the cheapest window and ready-by times shipped. What is left: a dashboard tile for the Immersion Scheduled Heating switch, a rule that heats in the cheapest window when the forecast is low, an export-against-cheapest-import check in the solar divert rule (where export pays more than the cheapest effective import, diverting solar loses money), valuing the immersion savings against the cheapest import rate, and letting the minimum-temperature rule wait for a cheap window that opens within about two hours when the water is only slightly under the minimum | The scheduled heating work in the changelog | 25 to 100 (low) | M |
| **S1 Take over charge schedules** (repair and one-click fix shipped in v0.8.0; what is left is below) | Raise a repair when any other charge slot is active in GivTCP. Offer a one-click fix in the repair that clears the conflicting slots, so grid charging happens in the cheapest window, with no new option. A leftover slot 2 can charge at a dearer rate. Charging in the window is capped by the charge rate times the window length | One install: most grid charge landed outside the cheapest window, and most of the energy in the dearer band could have moved | 75 to 100 (medium) | M |
| **S2 Add a nightly EV top-up and an EV charge window in the cheapest period** | Notify in the evening to plug in, then cap each session to the cheapest window plus a small top-up, through the charger's charge mode select (for example `select.myenergi_zappi_charge_mode`) or its own schedule. The gain needs a plug-in most nights. On session nights the window is already full | One install: re-pricing the EV sessions into the cheapest window cut their cost by about a quarter | 100 to 250 (low to medium) | L |
| **S6 Add a standing recommendations sensor and notification** | One sensor (proposed `saving_recommendations`) lists each suggestion with value per month, who acts and confidence. Send a notification when a new one appears. Build it after the items it reports | Existing roadmap | Not applicable (delivers the others) | M |

### Accuracy and clarity

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S12 Redefine the immersion savings sensors** | `immersion_savings_*` count diverted solar kWh only, and the heater is not managed, so they read near zero while the immersion draws far more from the grid. Rename, or add a cost by band for the immersion | One install: the monthly savings sensor read under 1 while the immersion used over 100 kWh | Not applicable | S |

### Setup and delivery

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S18 Require status checks on the `main` ruleset** | The ruleset has no required checks today (it has non-fast-forward, creation, pull request and code scanning rules). Require `lint`, `Tests (Python 3.13)`, `Tests (Python 3.14)`, `Home Assistant end-to-end`, `validate`, `HACS Action` and `Analyze (python)`. A repository settings change, not code | `.github/workflows/` | Not applicable | S |
| **S17 Add a per-appliance power list with roles** | Discover power sensors from the Home Assistant label `device_power`. Fall back to `device_class: power` in W with `state_class: measurement`, and skip entities with no statistics. Roles: `always_on`, `schedulable_cycle`, `discretionary`, `ev`, `immersion`. Foundation for C1 to C4 | One install: metered devices covered under half of the non-EV, non-immersion load | Not applicable (unlocks C1 to C4) | M |

---

## Could have

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **C10 Fix the first-setup currency and units form quirk** | Currency and units on the first-setup form behave unexpectedly. Not reproduced from the description: the price unit labels (for example `EUR/kWh`) follow the chosen currency only when the form is shown again after an error, and a clean submit stores the chosen currency with the default prices unchanged. Needs a description of what is expected | User request | Not applicable | S |
| **C25 Model battery round-trip loss in the charge simulation** | The forward simulation assumes no loss between the grid, the battery and the house, so it plans slightly too little charge. Add one efficiency factor, kept in one constant, and use it in the charge target and in any energy-balance estimate | Predbat comparison | Small (low) | S |
| **C26 Extend the charge window start for tariffs with no cheaper-than-base period after the cheapest** | The window end is only extended into cheaper-than-base periods that follow the cheapest one (shipped as a plan-sized charge window). A tariff whose cheapest period is the last cheap band before the base rate keeps a window the plan can outgrow. Start the window earlier, inside a cheaper-than-base period that precedes the cheapest, and move the pre-window write trigger with it. The cheapest hours then no longer come first, so write the start only as far back as the plan needs | Design of the plan-sized charge window | Not known. Depends on how many tariffs have this shape (low) | M |
| **C27 Date the standing charge, levy, VAT and discount** | Dated rate changes cover the unit rates only. The bill estimate reverses accumulated import cost with one VAT and discount factor and multiplies one standing charge by the days, so a change to any of them part-way through a period is wrong for the earlier days. Needs a per-day bill split in `calculate_bill` and the projected bill | Left out of the dated rate changes on purpose | Not applicable | M |
| **C1 Add standby baseline and unmetered load sensors** | `standby_baseline_w` (rolling 4 h minimum of rest-of-house load), `standby_cost_per_year`, `metered_always_on_w` and `unmetered_load_w`. They show where the base load goes. Needs S17 and M3 | One install: the overnight floor was a few hundred watts, and most of it was not metered | Not applicable (shows where cost goes, not a saving) | M |
| **C4 Add data-quality diagnostics** | Report a negative energy sensor, power sensors that are unavailable with no statistics, unit mismatches (a power sensor in kW) and delta counters marked `total_increasing`. Skip these in discovery. Needs S17 | Found while auditing one install's sensors | Not applicable | M |
| **C2 Detect appliance cycles** | Washing machine or dishwasher start, run length and kWh per cycle, with a suggestion to run it in the cheapest window or on sunny hours. Where the cheap rate is close to the export rate, moving to sunny hours pays little, so lead with the cheapest window. Needs S17 | One install: about half of cycles started in the base-rate band | 10 to 40 (low) | M |
| **C3 Nudge on always-on devices** | A notification first. Network equipment and plugs left on outside working hours draw power around the clock. Switching plugs off is opt-in only. Needs S17 and C1 | One install: always-on devices cost on the order of 100 a year combined | About 100 combined (low) | M |
| **C19 Arbitrate priority between EV, immersion and battery** | Settle who gets the surplus, and who gets the cheapest window when S1, S2 and S4 all want it. A shared supply limit belongs here, because the battery, EV and immersion together can draw more than the supply allows | The three items compete for the same window | Not applicable | M |
| **C18 Add on and off delays and smooth the net surplus** | Hold a sustained condition before switching (evcc: enable 1 minute, disable 3 minutes). Smooth the net surplus, not only solar, and seed the average from the first reading | External research | Not applicable | M |
| **C13 Test the Home Assistant floor version nightly** | `hacs.json` says 2026.2.0, but the end-to-end suite runs on one newer pinned release. A nightly run on the floor catches use of an API it lacks | Code review of v0.5.1 | Not applicable | S |
| **C9 Audit the icons** | 23 sensors need a review. Most descriptions set `icon=` while `icons.json` also holds icons, and `icon-translations` is `todo` in `quality_scale.yaml` | Icon audit. Code review of v0.5.1 | Not applicable | S |
| **C16 Document that export can read above the supplier meter** | The inverter-side measurement differs from the supplier meter by a small percentage | Bill reconciliation on one install | Not applicable | S |
| **C21 Make the charger minimum power depend on phases** | 1,380 W is right for a single phase only | External research | Not applicable | S |
| **C24 Support southern hemisphere seasons** | The winter and shoulder month lists in `const.py` are fixed calendar months for the northern hemisphere. Derive them from the latitude sign, or make them configurable | `REQUIREMENTS.md`, known limitations | Not applicable | S |
| **C22 Support Solcast multi-array** | Sum a second forecast sensor with the first. An unmerged branch, `givenergy-solcast-multi-array`, exists. A template sensor that sums the arrays works today | `REQUIREMENTS.md`, known limitations | Not applicable | M |
| **C20 Deadline heating and a pasteurisation cycle** | Reach a temperature by a set time in the cheapest window. Add a periodic pasteurisation cycle apart from the minimum temperature floor. The cycle needs a user-set target temperature | External research | Not applicable | M |
| **C5 Build the daily review into the integration** | A sensor or notification with the day's money, anomalies and recommendations. Needs M2, M3 and S6 | Existing roadmap | Not applicable | L |
| **C6 Replace remaining source-grep tests** | Tests that read a source file and assert a string, for example in `test_config_flow.py`, `test_coordinator.py` and `test_switch.py`. They fail on harmless edits and pass on broken behaviour. Re-measure before quoting counts | `CLAUDE.md`, code review of v0.5.1 | Not applicable | M |
| **C14 Move the currency unit to an ISO 4217 code** | Monetary sensors use a symbol. Home Assistant expects a code such as `EUR`. Changing it stops recording until each statistic is repaired, so it needs a repair plan first | `docs/long-term-statistics.md` | Not applicable | M |
| **C15 Add a calibration service for supplier bills** | Match the integration's totals to a bill. powercalc `calibrate_cost` is the model | Bill reconciliation on one install | Not applicable | M |
| **C17 Add a battery state of health sensor** | From the GivTCP calibrated and design capacity, plus battery temperature | External research | Not applicable | M |
| **C11 Pay down mypy debt** | 266 errors in the Home Assistant glue. `core/` is clean. Fix them, then add a mypy job to CI and close `strict-typing` in `quality_scale.yaml` | `quality_scale.yaml` | Not applicable | L |
| **C12 Move to the planned folder layout** | `coordinator.py` becomes a `coordinator/` package. The dashboard strategy (`strategy.py`) and `frontend/` move into `dashboard/`. Touches files every open branch edits, so do it between stacks | User request | Not applicable | M |
| **C23 Plan for GivEnergy administration** | Schedule the existing `export_energy_data` action for backups, detect and use `givenergy-local` if GivTCP is unavailable, and document migration to another inverter brand | `REQUIREMENTS.md`, non-goals | Not applicable | L |

---

## Nice to have

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **N14 Build a charge plan timeline card** | Only if core cards cannot express it | Existing roadmap | Not applicable | M |
| **N8 Track a battery health trend** | Chart state of health over time. Needs C17 | User request | Not applicable | S |
| **N7 Show appliance cost per use in notifications** | Needs C2 | User request | Not applicable | S |
| **N13 Plan the EV by departure time** | A departure-time plan over the tariff windows, as a signal for automations (evcc planner) | External research | Not applicable | M |
| **N4 Make immersion weather-aware** | Use weather as well as the solar forecast when choosing between cheap-rate and solar heating. | User request | Not applicable | M |
| **N9 Check appliance duty cycle** | Flag a rising duty cycle on a plug-metered appliance such as a fridge. The plug may carry other appliances | One install: a fridge plug averaged about 50 W, or about 460 kWh a year | 40 to 50 if replaced (low) | M |
| **N5 Speak a daily summary** | A voice summary built on `today_summary` | User request | Not applicable | S |
| **N6 Add per-room energy cards** | Dashboard cards from the device list. Needs S17 | User request | Not applicable | M |
| **N10 Infer occupancy and routine from load shape** | Opt-in, and always labelled as inference | Existing roadmap | Not applicable | M |
| **N1 Charge by carbon intensity** | Carbon intensity sensors exist since v0.3.0. Use them to prefer low-carbon import and export. Cost-led today, so it needs a decision first | Existing roadmap | Not applicable | M |
| **N2 Compare tariffs live** | Compare plans on persisted per-slot data (issue 114). Needs a 30 minute import and export accumulator first. `compare_tariff` covers a billing period today | Issue 114 | Not applicable | L |
| **N16 Add translations** | `ga`, `sv` and `nb`. A community contribution | Existing roadmap | Not applicable | S |
| **N15 Rework the EV step of the config flow** | Show discovered chargers, confirm entity mapping, ask car-specific questions, test that the mode entity is writable | Existing roadmap | Not applicable | M |
| **N17 Tidy the engineering plumbing** | Read GivTCP's own write count when present. Remove the `strings.json` and `translations/en.json` duplication. Replace `logging.py` (about 425 lines) with a logger filter. Move fields set after the engine runs into the engine call. Add issue templates that ask for diagnostics and the GivTCP version, and decision records for the cycle definition and tariff model | Code review of v0.5.1 | Not applicable | M |
| **N3 Support multiple inverters** | Sum solar and battery SoC across GivTCP inverters, for a gateway and AIO systems | Existing roadmap | Not applicable | M |
| **N11 Support more hardware** | Multiple EV chargers (cost per charger, priority), storage heaters (charge in the cheapest window, needs a plug or CT), a second immersion element or heat pump cylinder (COP-aware cost), heat pump integration, demand response from grid operator signals | Existing roadmap | Not applicable | L |
| **N12 Read a per-slot solar curve and day-ahead tariffs** | Use a per-period forecast attribute instead of a fixed bell curve (depends on what Solcast exposes). Dynamic day-ahead tariffs need a verified source first | Existing roadmap | Not applicable | L |

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
| Forced battery export or discharge windows, meaning writing export or discharge schedules, rates or reserve to the inverter | They add write risk and complexity. Payment for exported energy is the part most likely to be reduced or dropped by suppliers and grid operators, so a plan built on it ages badly. The integration stays with charging, immersion and EV control. It does not advise export either, so the pre-boost export sensors were removed |
| Multi-night planning and choosing the charge window by price | With a fixed timed tariff the cheapest window is the same every night. Revisit if dynamic or half-hourly tariffs are added |

---

## Dependencies and order

1. **EV power is confirmed.** It reads the real charger. S5, S2 and C1 can rely on it, and the load baseline excludes the EV.
2. **One writer for the charge schedule.** S1 and S5 write it. All go through `GivTCPWriter`, so the verified read-back and write counting apply.
3. **S17 before C1 to C4, N6 and N7.** The device list is the foundation. C1 comes before C3. C2 comes before N7. C17 comes before N8.
4. **S1, S2 and S4 share the cheap windows.** The battery, the EV and the immersion can together draw more than the supply allows. Do C19 or add a supply limit check before enabling more than one by default.
5. **C12 between stacks, then C11.** The layout move touches `coordinator.py`. Fix the types after the move, so each error is fixed once at its final path.

---

## Open questions

Comment on a GitHub issue to weigh in.

1. **Do most users plug the car in most nights?** The top of the S2 range assumes it. Without it, S2 is not worth an L.

---

## Known limitations

| Limitation | Impact | Tracked as |
|---|---|---|
| Only one EV charger tracked for cost | Homes with several EVs show incomplete cost | N11 |
| Zappi Eco+ competes with the battery for solar | Suboptimal solar allocation. The integration never pauses the Zappi, because the two systems are separate | Won't have |
| Forecast.Solar is less accurate for east-west arrays | Charge target may be slightly off. A template sensor that sums the arrays works | C22 |
| Bill prediction assumes constant daily usage | Inaccurate early in the billing period | Improves as data builds up |
| GivTCP must be installed and running | Hard dependency. Detection is in place | C23 |
| The standing charge, levy, VAT and discount apply from the moment they are saved, not from a date | A change part-way through a bill period makes the bill estimate wrong for the days before it | C27 |
| Season rules use northern hemisphere months | Winter behaviour starts in the wrong months in the southern hemisphere | C24 |
| Cycle count is an estimate when GivTCP publishes no BMS counter | Can differ from the battery's own counter | Counts discharge only since v0.4.0 |
| Monetary sensors use a currency symbol as the unit | Newer Home Assistant versions may reject statistics | C14 |

---
