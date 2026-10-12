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
| **S5 Make the overnight charge target load-aware** | Use a rolling non-EV evening load so the battery lasts until the cheap window and does not run flat into base-rate import. When solar matches the forecast but the battery still runs flat, load caused the miss | One install: on one evening the battery ran flat several hours before the cheap window and about 7 kWh came in at the base rate. A simple open-source script charges a home battery overnight only if tomorrow's solar will not cover the day, or if the battery is nearly empty ahead of an expensive morning ([Charge-battery](https://github.com/mhurk/Charge-battery)). That is the same two cases this item targets. | 35 to 65 (low to medium) | M |
| **S4 Refine scheduled immersion heating** | Scheduled heating in the cheapest window and ready-by times shipped. What is left: a dashboard tile for the Immersion Scheduled Heating switch, a rule that heats in the cheapest window when the forecast is low, an export-against-cheapest-import check in the solar divert rule (where export pays more than the cheapest effective import, diverting solar loses money), valuing the immersion savings against the cheapest import rate, and letting the minimum-temperature rule wait for a cheap window that opens within about two hours when the water is only slightly under the minimum | The scheduled heating work in the changelog. Predbat's [iBoost model](https://springfall2008.github.io/batpred/customisation/) has a daily energy cap, a minimum SoC and a gas price scale. A personal script boosts an immersion for a time set by the battery's charge ([Smart Immersion Heater Booster](https://github.com/robkwhitehouse/Smart-Immersion-Heater-Booster)). The diverter's per-step rules (price test, daily cap, minimum power, minimum state of charge) are specified in SPEC-004 (issue #371). | 25 to 100 (low) | M |
| **S1 Take over charge schedules** (repair and one-click fix shipped in v0.8.0; what is left is below) | Raise a repair when any other charge slot is active in GivTCP. Offer a one-click fix in the repair that clears the conflicting slots, so grid charging happens in the cheapest window, with no new option. A leftover slot 2 can charge at a dearer rate. Charging in the window is capped by the charge rate times the window length | One install: most grid charge landed outside the cheapest window, and most of the energy in the dearer band could have moved. In v0.19 a dashboard warning appears when something else sets the charge target. PALM's SmartTarget, Predbat and the GivEnergy app can all do it, and an EMS plant reasserts its own settings. | 75 to 100 (medium) | M |
| **S2 Add a nightly EV top-up and an EV charge window in the cheapest period** | Notify in the evening to plug in, then cap each session to the cheapest window plus a small top-up, through the charger's charge mode select (for example `select.myenergi_zappi_charge_mode`) or its own schedule. The gain needs a plug-in most nights. On session nights the window is already full | One install: re-pricing the EV sessions into the cheapest window cut their cost by about a quarter | 100 to 250 (low to medium) | L |
| **S6 Add a standing recommendations sensor and notification** | One sensor (proposed `saving_recommendations`) lists each suggestion with value per month, who acts and confidence. Send a notification when a new one appears. Build it after the items it reports | Existing roadmap | Not applicable (delivers the others) | M |

### Accuracy and clarity

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S12 Redefine the immersion savings sensors** | `immersion_savings_*` count diverted solar kWh only, and the heater is not managed, so they read near zero while the immersion draws far more from the grid. Rename, or add a cost by band for the immersion | One install: the monthly savings sensor read under 1 while the immersion used over 100 kWh | Not applicable | S |

### Setup and delivery

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S18 Require status checks on the `main` ruleset** | The ruleset has no required checks today (it has non-fast-forward, creation, pull request and code scanning rules). Require `lint`, `Tests (Home Assistant 2026.5.0)`, `Tests (Home Assistant latest)`, `Home Assistant end-to-end (2026.5.0)`, `Home Assistant end-to-end (latest)`, `validate`, `HACS Action` and `Analyze (python)`. Leave the two beta jobs out. A repository settings change, not code | `.github/workflows/` | Not applicable | S |
| **S19 Add an action that exports an anonymised system profile** | An action that writes a redacted list of the inverter's entities (ids with serials replaced, states, units and attributes), the GivTCP version, the inverter type, the number of battery modules and which charge slots exist, then shows a notification with a download link. Users attach it to an issue. It makes every inverter configuration testable without screenshots, and it is how support for All-In-One, gateway, three-phase and EMS systems gets proved on real hardware | givenergy-hass has a capture action and givenergy-cli can export a redacted plant dump (serial numbers redacted by default) ([givenergy-hass](https://github.com/dewet22/givenergy-hass), [givenergy-cli](https://pypi.org/project/givenergy-cli/1.5.0/)) | Not applicable | M |
| **S17 Add a per-appliance power list with roles** | Discover power sensors from the Home Assistant label `device_power`. Fall back to `device_class: power` in W with `state_class: measurement`, and skip entities with no statistics. Roles: `always_on`, `schedulable_cycle`, `discretionary`, `ev`, `immersion`. Foundation for C1 to C4 | One install: metered devices covered under half of the non-EV, non-immersion load. The Octopus Energy integration can track the cost of any other entity and compare it with another tariff ([repository](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)). PV Excess Control tracks savings, the self-consumption ratio and energy statistics ([README](https://github.com/InventoCasa/PV-Excess-Control)). | Not applicable (unlocks C1 to C4) | M |

---

## Could have

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **C10 Fix the first-setup currency and units form quirk** | Currency and units on the first-setup form behave unexpectedly. Not reproduced from the description: the price unit labels (for example `EUR/kWh`) follow the chosen currency only when the form is shown again after an error, and a clean submit stores the chosen currency with the default prices unchanged. Needs a description of what is expected | User request | Not applicable | S |
| **C28 Add an away mode** | A switch, or a number of days away, that stops away days from being learned as normal load and lets the plan recover afterwards. Today a week away fills the learned profile with low-load days, so the plan under-charges for several days after you return. Predbat matches load history by holiday state, so a day at home is predicted from days at home | Predbat: [holiday mode](https://springfall2008.github.io/batpred/customisation/#holiday-mode) and [`days_previous_auto`](https://springfall2008.github.io/batpred/apps-yaml/). Behaviour specified in issue #370 (SPEC-003): away days matched per sample, a fallback scale for the first day away and the day home, a drop-the-lowest-day filter | Not measured (low) | S |
| **C32 Say when the Solcast P10 attribute is switched off** | The pessimistic forecast reads the `estimate10` attribute of the Solcast tomorrow sensor. Solcast lets users switch that attribute off, and the integration then has no pessimistic estimate and says nothing. Detect a Solcast forecast sensor with no `estimate10`, and show it in diagnostics or as a repair with the setting to change | Solcast README: [sensors and attributes](https://github.com/BJReplay/ha-solcast-solar) (options `attr_brk_estimate10` and `attr_brk_hourly`). The attribute is read in `coordinator.py`. Check the default first (card FS1) | Not applicable | S |
| **C29 Read the battery capacity live** | Take the capacity from GivTCP on every cycle (`Battery_Capacity_kWh`, or the module-based `Battery_Capacity_kWh_calc`) so adding a module or an ageing battery needs no visit to Configure. Check which of the two matches the usable energy on each system type | The config diet review (`docs/design/CONFIG_DIET.md`, follow-up 1). GivTCP [datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md). givenergy-hass probes the battery count at start-up and offers a re-detect action | Not applicable | S |
| **C25 Model battery round-trip loss in the charge simulation** | The forward simulation assumes no loss between the grid, the battery and the house, so it plans slightly too little charge. Add one efficiency factor, kept in one constant, and use it in the charge target and in any energy-balance estimate | Predbat comparison. Predbat tunes inverter loss and battery loss, around 4% each for a hybrid ([configuration guide](https://springfall2008.github.io/batpred/configuration-guide/)). | Small (low) | S |
| **C26 Extend the charge window start for tariffs with no cheaper-than-base period after the cheapest** | The window end is only extended into cheaper-than-base periods that follow the cheapest one (shipped as a plan-sized charge window). A tariff whose cheapest period is the last cheap band before the base rate keeps a window the plan can outgrow. Start the window earlier, inside a cheaper-than-base period that precedes the cheapest, and move the pre-window write trigger with it. The cheapest hours then no longer come first, so write the start only as far back as the plan needs | Design of the plan-sized charge window | Not known. Depends on how many tariffs have this shape (low) | M |
| **C27 Date the standing charge, levy, VAT and discount** | Dated rate changes cover the unit rates only. The bill estimate reverses accumulated import cost with one VAT and discount factor and multiplies one standing charge by the days, so a change to any of them part-way through a period is wrong for the earlier days. Needs a per-day bill split in `calculate_bill` and the projected bill | Left out of the dated rate changes on purpose | Not applicable | M |
| **C1 Add standby baseline and unmetered load sensors** | `standby_baseline_w` (rolling 4 h minimum of rest-of-house load), `standby_cost_per_year`, `metered_always_on_w` and `unmetered_load_w`. They show where the base load goes. Needs S17 and M3 | One install: the overnight floor was a few hundred watts, and most of it was not metered | Not applicable (shows where cost goes, not a saving) | M |
| **C4 Add data-quality diagnostics** | Report a negative energy sensor, power sensors that are unavailable with no statistics, unit mismatches (a power sensor in kW) and delta counters marked `total_increasing`. Skip these in discovery. Needs S17 | Found while auditing one install's sensors | Not applicable | M |
| **C2 Detect appliance cycles** | Washing machine or dishwasher start, run length and kWh per cycle, with a suggestion to run it in the cheapest window or on sunny hours. Where the cheap rate is close to the export rate, moving to sunny hours pays little, so lead with the cheapest window. Needs S17 | One install: about half of cycles started in the base-rate band | 10 to 40 (low) | M |
| **C3 Nudge on always-on devices** | A notification first. Network equipment and plugs left on outside working hours draw power around the clock. Switching plugs off is opt-in only. Needs S17 and C1 | One install: always-on devices cost on the order of 100 a year combined | About 100 combined (low) | M |
| **C19 Arbitrate priority between EV, immersion and battery** | Settle who gets the surplus, and who gets the cheapest window when S1, S2 and S4 all want it. A shared supply limit belongs here, because the battery, EV and immersion together can draw more than the supply allows | The three items compete for the same window. OpenEVSE's Home Assistant integration uses a claim and override system, so several callers can queue, override or limit a charge safely ([README](https://github.com/firstof9/openevse)). PV Excess Control offers three battery strategies: battery first, appliance first and balanced ([README](https://github.com/InventoCasa/PV-Excess-Control)). Shedding order and the three battery protections are specified in SPEC-007 (issue #374). | Not applicable | M |
| **C31 Set the charge mode of Wallbox, OCPP, Ohme and Easee chargers** | The EV code finds five brands but sets only the Zappi's mode. Map the logical "use surplus only" to each brand's option. Never stop, pause or fast charge, as the safety rules say. Needs an owner of each brand to supply entity lists first. The GivEnergy charger arrives in v0.19, and its import cap and session cap are candidates here | Predbat starts and stops a Zappi, an Ohme and a GivEnergy charger from its car plan ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)). GivTCP's GivEVC controls ([datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)). evcc connects chargers through templates for OCPP, Modbus and HTTP ([repository](https://github.com/evcc-io/evcc)). OpenEVSE has a solar divert mode ([README](https://github.com/firstof9/openevse)) | Not applicable | M |
| **C18 Add on and off delays and smooth the net surplus** | Hold a sustained condition before switching (evcc: enable 1 minute, disable 3 minutes). Smooth the net surplus, not only solar, and seed the average from the first reading | External research. PV Excess Control sheds appliances when the battery falls below a minimum and allows a small amount of grid power to top up a load ([README](https://github.com/InventoCasa/PV-Excess-Control)). Behaviour is specified in issue #374 (SPEC-007): an averaged surplus gates turn-on and an instantaneous one gates shedding, with a minimum count of good samples and an off threshold. | Not applicable | M |
| **C9 Audit the icons** | 23 sensors need a review. Most descriptions set `icon=` while `icons.json` also holds icons, and `icon-translations` is `todo` in `quality_scale.yaml` | Icon audit. Code review of v0.5.1 | Not applicable | S |
| **C16 Document that export can read above the supplier meter** | The inverter-side measurement differs from the supplier meter by a small percentage | Bill reconciliation on one install | Not applicable | S |
| **C21 Make the charger minimum power depend on phases** | 1,380 W is right for a single phase only | External research | Not applicable | S |
| **C34 Offer cheap-period sensors for the user's own automations** | A binary sensor that is on during the cheapest window, and one for the cheapest N hours between two times, so a dishwasher or a heat pump can follow the tariff without a template. Check which of these already exist before adding any. The Octopus Energy integration's target rate sensors are described by its author as one of its key features, and he is moving them into a separate data-source-neutral integration | [Octopus Energy target rate discussion](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/discussions/1305), [target rate sensors in use](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/discussions/284). PV Excess Control has tariff integration ([README](https://github.com/InventoCasa/PV-Excess-Control)). The selection rules (continuous and intermittent, ties, limits, weighting) are specified in issue #373 (SPEC-006) | Not applicable | S |
| **C30 Offer an action that exposes a recommended set of entities to Assist and LLM tools** | Home Assistant does not expose `power`, `energy` or `battery` sensors to voice assistants by default, so "what is my battery at?" returns nothing until they are exposed. An idempotent action that only ever exposes (never un-exposes) the headline sensors. Do not ship aliases: the registry cannot tell ours from the user's | givenergy-hass has one ([README](https://github.com/dewet22/givenergy-hass)). Background: [community thread](https://community.home-assistant.io/t/wth-are-all-new-entities-exposed-to-assist-by-default/803889) | Not applicable | S |
| **C33 Document and test two more forecast sources** | Open-Meteo Solar Forecast is free, needs no account, and has `watts` and `wh_period` attributes (a tomorrow energy sensor is likely but not confirmed). Helios Forecast learns from the user's own production and offers an action `helios_forecast.get_forecast`. Both are common choices for people without a Solcast account. Confirm each exposes a usable tomorrow sensor, add them to the wizard's suggestions and the docs, and note what each does about dampening and shading | [Open-Meteo Solar Forecast thread](https://community.home-assistant.io/t/open-meteo-solar-forecast/733073), [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast), [Solar Forecast Card](https://github.com/AshGSmith/solar-forecast-card) (lists the supported providers) | Not applicable | S |
| **C24 Support southern hemisphere seasons** | The winter and shoulder month lists in `const.py` are fixed calendar months for the northern hemisphere. Derive them from the latitude sign, or make them configurable | `REQUIREMENTS.md`, known limitations. In v0.19 the months become settings with defaults from the latitude. | Not applicable | S |
| **C22 Support Solcast multi-array** | Sum a second forecast sensor with the first. An unmerged branch, `givenergy-solcast-multi-array`, exists. A template sensor that sums the arrays works today | `REQUIREMENTS.md`, known limitations. Predbat takes several arrays as a list in its forecast settings ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)). | Not applicable | M |
| **C20 Deadline heating and a pasteurisation cycle** | Reach a temperature by a set time in the cheapest window. Add a periodic pasteurisation cycle apart from the minimum temperature floor. The cycle needs a user-set target temperature | External research | Not applicable | M |
| **C5 Build the daily review into the integration** | A sensor or notification with the day's money, anomalies and recommendations. Needs M2, M3 and S6 | Existing roadmap | Not applicable | L |
| **C14 Move the currency unit to an ISO 4217 code** | Monetary sensors use a symbol. Home Assistant expects a code such as `EUR`. Changing it stops recording until each statistic is repaired, so it needs a repair plan first | `docs/long-term-statistics.md` | Not applicable | M |
| **C15 Add a calibration service for supplier bills** | Match the integration's totals to a bill. powercalc `calibrate_cost` is the model | Bill reconciliation on one install | Not applicable | M |
| **C17 Add a battery state of health sensor** | From the GivTCP calibrated and design capacity, plus battery temperature | External research. GivTCP publishes stack state of health and per-module values ([datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)). See N19. | Not applicable | M |
| **C11 Pay down mypy debt** | 266 errors in the Home Assistant glue. `core/` is clean. Fix them, then add a mypy job to CI and close `strict-typing` in `quality_scale.yaml` | `quality_scale.yaml` | Not applicable | L |
| **C12 Move to the planned folder layout** | `coordinator.py` becomes a `coordinator/` package. The dashboard strategy (`strategy.py`) and `frontend/` move into `dashboard/`. Touches files every open branch edits, so do it between stacks | User request | Not applicable | M |
| **C23 Plan for GivEnergy administration** | GivEnergy Ltd entered administration on 9 April 2026 and ceased trading. The software company that runs the cloud is separate. Its free tier keeps local control and third-party software on the home network, and moves remote access, history and automation such as Smart Tariff into a paid Premium tier ([FAQ](https://givenergy.cloud/givenergy-faq)). What is left: schedule the existing `export_energy_data` action for backups, document moving to another inverter brand, and plan a second backend that does not need GivTCP (N23). | `REQUIREMENTS.md`, non-goals. [Administrator's statement](https://daily-focus.co.uk/2026/04/givenergy-ceases-trading-with-all-jobs-lost/). | Not applicable | L |

---

## Nice to have

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **N14 Build a charge plan timeline card** | Only if core cards cannot express it | Existing roadmap. Predbat's [plan card](https://springfall2008.github.io/batpred/predbat-plan-card/) shows rate, status, limit, forecast solar, load, car and diverter energy per slot. Energy Conductor shows twelve hours of history and twelve of forecast on one axis ([README](https://github.com/dewet22/givenergy-hass)). | Not applicable | M |
| **N20 Add a Glance view and a wall-panel view** | One sentence for the system's state, three large numbers and a few health pills, with no tabs, for a wall tablet or a phone. Built from core cards | givenergy-hass has flow, glance, analyst and kiosk modes ([README](https://github.com/dewet22/givenergy-hass)) | Not applicable | M |
| **N8 Track a battery health trend** | Chart state of health over time. Needs C17 | User request. GivTCP publishes stack state of health and per-module values ([datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)). See N19. | Not applicable | S |
| **N19 Show per-module battery health** | GivTCP publishes each battery module's state of charge, capacity, cycles and temperature, and for high-voltage stacks the state of health and cell voltages. Start with the module list and the stack's state of health. Needs C17 | GivTCP [datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md). givenergy-hass shows per-cell voltage and temperature with a heat map card ([README](https://github.com/dewet22/givenergy-hass)) | Not applicable | M |
| **N7 Show appliance cost per use in notifications** | Needs C2 | User request. The Octopus Energy integration can track the cost of any other entity and compare it with another tariff ([repository](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)). PV Excess Control tracks savings, the self-consumption ratio and energy statistics ([README](https://github.com/InventoCasa/PV-Excess-Control)). | Not applicable | S |
| **N13 Plan the EV by departure time** | A departure-time plan over the tariff windows, as a signal for automations (evcc planner) | External research. evcc plans charging to a departure time, varies it on surplus and battery state ([roundup](https://diyai.io/ai-tools/engineering/best-ai-home-energy-management-tools/)). Predbat has a [car charging plan](https://springfall2008.github.io/batpred/car-charging/). The slot-selection and fallback rules are specified in SPEC-008 (issue #375). | Not applicable | M |
| **N4 Make immersion weather-aware** | Use weather as well as the solar forecast when choosing between cheap-rate and solar heating. | User request. A community project sizes an overnight immersion top-up from tomorrow's forecast and adds weather compensation from the outside temperature, heating to the maximum when the previous day's solar top-up was low ([thread](https://community.home-assistant.io/t/smart-immersion-heating-for-domestic-hot-water/536281)). EMHASS models a water tank as thermal storage ([documentation](https://emhass.readthedocs.io/)). | Not applicable | M |
| **N21 Raise the reserve ahead of a severe weather alert** | Keep the battery fuller when an alert is active. **Read first** how Predbat's weather alert system works and which alert source is trustworthy for each country. Nothing was read beyond its name | Predbat lists a "Weather Alert System" in its [apps.yaml documentation](https://springfall2008.github.io/batpred/apps-yaml/) | Not measured (low) | M |
| **N9 Check appliance duty cycle** | Flag a rising duty cycle on a plug-metered appliance such as a fridge. The plug may carry other appliances | One install: a fridge plug averaged about 50 W, or about 460 kWh a year | 40 to 50 if replaced (low) | M |
| **N5 Speak a daily summary** | A voice summary built on `today_summary` | User request | Not applicable | S |
| **N6 Add per-room energy cards** | Dashboard cards from the device list. Needs S17 | User request | Not applicable | M |
| **N10 Infer occupancy and routine from load shape** | Opt-in, and always labelled as inference | Existing roadmap | Not applicable | M |
| **N1 Charge by carbon intensity** | Carbon intensity sensors exist since v0.3.0. Use them to prefer low-carbon import and export. Cost-led today, so it needs a decision first | Existing roadmap. PALM's load sequencer switches loads on time, temperature, battery charge and CO2 per kWh ([PALM](https://github.com/salewis38/palm)). | Not applicable | M |
| **N2 Compare tariffs live** | Compare plans on persisted per-slot data (issue 114). Needs a 30 minute import and export accumulator first. `compare_tariff` covers a billing period today | Issue 114 | Not applicable | L |
| **N16 Add translations** | `ga`, `sv` and `nb`. A community contribution | Existing roadmap | Not applicable | S |
| **N15 Rework the EV step of the config flow** | Show discovered chargers, confirm entity mapping, ask car-specific questions, test that the mode entity is writable | Existing roadmap | Not applicable | M |
| **N17 Tidy the engineering plumbing** | Read GivTCP's own write count when present. Remove the `strings.json` and `translations/en.json` duplication. Replace `logging.py` (about 425 lines) with a logger filter. Move fields set after the engine runs into the engine call. Add issue templates that ask for diagnostics and the GivTCP version, and decision records for the cycle definition and tariff model | Code review of v0.5.1 | Not applicable | M |
| **N3 Support multiple inverters** | Sum solar and battery SoC across GivTCP inverters, for a gateway and AIO systems | Existing roadmap. In v0.19 the integration finds All-In-One, gateway, three-phase and several inverters and says which were tested on real hardware. Known traps are in the design notes in `docs/design/`: a parallel All-In-One is a child inverter that may ignore commands (the [official API](https://givenergy.cloud/docs/api/v1)), a Gateway offers few or no controls, and an EMS plant reasserts settings. Detection, gating and caching of system types are specified in issue #372 (SPEC-005). | Not applicable | M |
| **N23 Add a second inverter backend using direct local Modbus** | After the backend interface in v0.19, a second backend would remove the GivTCP add-on and its MQTT broker for people who do not run them, and is a way to keep working if GivTCP stops being maintained (see C23). The candidate is givenergy-hass (local Modbus). It exposes enable charge, charge target SOC and slot times, leaves out slots 3 to 10, and offers no controls through a Gateway. It reports that two local clients can poll one inverter. Write a new adapter from the interface. Copy no code. Needs fixtures for each system type | [givenergy-hass](https://github.com/dewet22/givenergy-hass), [givenergy-modbus](https://github.com/dewet22/givenergy-modbus) (supported-hardware table), [givenergy-cli](https://pypi.org/project/givenergy-cli/1.5.0/) | Not applicable | L |
| **N11 Support more hardware** | Multiple EV chargers (cost per charger, priority), storage heaters (charge in the cheapest window, needs a plug or CT), a second immersion element or heat pump cylinder (COP-aware cost), heat pump integration, demand response from grid operator signals | Existing roadmap. In v0.19 the integration finds All-In-One, gateway, three-phase and several inverters and says which were tested on real hardware. Known traps are in the design notes in `docs/design/`: a parallel All-In-One is a child inverter that may ignore commands (the [official API](https://givenergy.cloud/docs/api/v1)), a Gateway offers few or no controls, and an EMS plant reasserts settings. Detection, gating and caching of system types are specified in issue #372 (SPEC-005). | Not applicable | L |
| **N22 Charge in a second cheap window** | Some tariffs have two cheap periods a day, for example an afternoon one. Needs an inverter with a second charge slot (a Homey app listing says Gen 1 and Gen 2 have one) and a target rule for each window. Related to C26 | PALM added an afternoon Cosy charge period ([PALM](https://github.com/salewis38/palm)). [Homey app listing](https://homey.app/en-gb/app/io.jak.givenergy/) | Not measured (low) | L |
| **N12 Read a per-slot solar curve and day-ahead tariffs** | Use the forecast provider's per-period attribute instead of a fixed bell curve (in v0.19, where the provider exposes one). Dynamic day-ahead tariffs still need a verified source first. | Existing roadmap. Predbat reads rates and the standing charge from the Octopus Energy integration ([energy rates](https://springfall2008.github.io/batpred/energy-rates/)). The GivEnergy Tariff Optimiser add-on schedules charge slots on Agile ([post](https://community.home-assistant.io/t/givenergy-tariff-optimiser-automated-octopus-agile-battery-scheduling-arbitrage-add-on/1021514)). | Not applicable | L |
| **N24 Correct the solar forecast by matching similar past conditions** | Instead of one daily accuracy ratio, look up past days (or hours) whose forecast conditions were similar and read what the installation actually produced then, as a ratio to the forecast. The median ratio gives a site-specific correction and the 10th and 90th percentile ratios give a data-driven band. Blend back to the plain forecast when few similar days exist. Needs the production and forecast history the integration already keeps, and ideally a weather source. Specified in issue #376 (SPEC-009) | Helios Forecast does this per hour with a physical model ([repository](https://github.com/ReikanYsora/Helios-Forecast)) | Not measured (low) | L |
| **N18 Control the alternative water heating from the cheapest-source advice** | If the home has a switch for the oil or gas boiler, the heat pump or its water heating channel, follow the Water Heating Cheapest Source advice by switching it, with dry run, the switch hold and manual overrides as for the immersion. Needs its own opt-in switch and a design for the other system's own timers. Advice only until then | User request | Not applicable | M |

---

## Won't have for now

| Decision | Why |
|---|---|
| Companion HACS repositories (Power Flow Card, Energy History Card, Charge Plan Timeline Card, HTML Report Templates) | Wait until sensor naming is stable at v1.0 |
| An integration-owned dashboard that rewrites the user's Lovelace | It relies on internal Home Assistant APIs and overwrites user edits |
| A sidebar panel, a rebuild of power-flow-card-plus or apexcharts, a webpack or TypeScript pipeline | Too much to maintain for the gain |
| Linear programming or genetic optimisers and machine learning forecasters (EMHASS, EOS) | Too heavy for this integration. evcc's own optimiser is described in its documentation as informational only and does not yet control the home battery ([evcc optimiser](https://docs.evcc.io/en/features/optimizer.md)). EMHASS needs a solver and a trained model to maintain ([documentation](https://emhass.readthedocs.io/)). |
| Copying code, comments, names or structure from other projects | We build our own. Studying how they work and writing our own specification, then building from it, is allowed. The specification contains no code |
| Pausing or stopping the Zappi to protect the battery | Removed in v0.2.1. The two systems are separate and stopping the Zappi does not protect the battery |
| Cloud APIs | The integration is local, see the non-goals in `REQUIREMENTS.md` |
| Forced battery export or discharge windows, meaning writing export or discharge schedules, rates or reserve to the inverter | They add write risk and complexity. Payment for exported energy is the part most likely to be reduced or dropped by suppliers and grid operators, so a plan built on it ages badly. The integration stays with charging, immersion and EV control. It does not advise export either, so the pre-boost export sensors were removed |
| Multi-night planning and choosing the charge window by price | With a fixed timed tariff the cheapest window is the same every night. Revisit if dynamic or half-hourly tariffs are added |
| Variable-power immersion diversion (a dimmer or phase-angle controller) | Needs special hardware. The integration switches a plain switch, and hardware diverters (iBoost, Eddi) already vary the power |
| Uploading to PVOutput, and a general time-and-temperature load sequencer (PALM) | Not asked for. Long-term analysis is covered by Home Assistant statistics and the Energy dashboard |

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

2. **Which GivTCP versions are supported?** GivTCP 3.6 changed signs, entity sets and pause entities. The release supports what its fixtures prove.

3. **On inverters with per-slot targets, does `Target_SOC` stop a charge?** The write sequence assumes it does. A real charge on such an inverter settles it.

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
| Tested on one single-phase hybrid | All-In-One, gateway, three-phase, EMS and several-inverter systems are found but not proved on real hardware | N3, S19 |
| A parallel All-In-One is a child inverter and a Gateway may offer no controls | A write can read back correctly and change nothing. The integration controls the gateway or the plant device only | N3, N23 |
| On AC-coupled and All-In-One systems the solar energy counters may count battery output | Forecast accuracy and solar share could read high. Not yet verified | N11 |
| The immersion is switched on and off, never varied | A small surplus may be partly met from the battery or the grid | Won't have |
| One charge window | A second cheap period is not used | N22 |
| An away period fills the learned load with low days | The plan under-charges for several days after you return | C28 |

---
