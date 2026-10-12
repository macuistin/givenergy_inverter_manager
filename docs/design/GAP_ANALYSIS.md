# What other GivEnergy systems do that this integration does not

> **Where the parts of the 0.19 plan are.** This plan was written as one file in four parts. References such as "Part A" or "Part B section 1.5" mean:
> 
> | Part | File |
> |---|---|
> | Part 0 (instructions for the agent) | [RELEASE_0.19_AGENT_NOTES.md](RELEASE_0.19_AGENT_NOTES.md) |
> | Part A (the release brief) | [RELEASE_0.19_BRIEF.md](RELEASE_0.19_BRIEF.md) |
> | Part B (design pack for the roadmap features) | [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md) |
> | Part C (specifications extracted from other projects) | [specs/](specs/README.md) |
> | Part D (gap analysis) | [GAP_ANALYSIS.md](GAP_ANALYSIS.md) |
> 

## Part D: What other GivEnergy systems do that this integration does not (reference, read on demand)

**Scope:** other projects and products that handle GivEnergy systems, compared with this integration at v0.18.0. **Method:** each project's own README, documentation, release notes or published API, read in October 2026. Nothing was run. **Method:** specification first (Part C (specifications)). Where code is public it can be studied to write a specification in our own words, and we build from the specification. Copying code, comments, names or structure is ruled out.
**Where each gap goes:** every row has a roadmap id. New ids are listed in Appendix F of `Part A`, with the exact text to add to `ROADMAP.md`.

**What was not read:** openHAB, Solar Assistant and Home Battery Control. evcc, EMHASS and PV Excess Control are covered in section F from their own pages, not run. Energy Conductor was read only through another project's README, not run. Predbat's documentation was read for its apps.yaml, configuration guide, customisation, output data and energy rates pages, not every page.

---

### A. Gaps: things others do that this integration does not

| Theme | Capability | Who has it | This integration today | Roadmap | v0.19 |
|---|---|---|---|---|---|
| **Charge plan** | Re-check the plan near the end of the cheap window and correct the target | PALM calculates a second forecast an hour before off-peak ends ([PALM](https://github.com/salewis38/palm)) | One write a day, a missed write is not retried | Delivered in v0.19, so no roadmap row | Yes: retry and re-plan |
| | Use the forecast's own half-hourly shape | Predbat reads Solcast, Forecast.Solar and Open-Meteo ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)) | Fixed bell curve centred on 13:00 | N12 | Yes, where the provider exposes it |
| | Season and winter rules that are not tied to one hemisphere | PALM lets the user pick the months ([forum](https://community.home-assistant.io/t/givtcp-and-smart-target-palm/692530)) | Fixed northern months | C24 | Yes |
| | Battery and inverter loss in the plan | Predbat's `inverter_loss` and `battery_loss`, about 4% each for a hybrid ([configuration guide](https://springfall2008.github.io/batpred/configuration-guide/)) | No loss modelled | C25 | No |
| | **Holiday or away mode** | Predbat matches load history by holiday state, so away days do not poison the profile ([customisation](https://springfall2008.github.io/batpred/customisation/#holiday-mode)) | None. A week away leaves the learned profile low for days after | **C28 (new)** | No |
| | A second charge window (an afternoon cheap period) | PALM added an afternoon Cosy period ([PALM](https://github.com/salewis38/palm)) | One window | **N22 (new)** | No |
| | Dynamic half-hourly tariffs, export planning | Predbat ([configuration guide](https://springfall2008.github.io/batpred/configuration-guide/)); GivEnergy Tariff Optimiser add-on ([post](https://community.home-assistant.io/t/givenergy-tariff-optimiser-automated-octopus-agile-battery-scheduling-arbitrage-add-on/1021514)) | Fixed and time-of-use rates only. No export planning, by decision | N12, Won't have | No |
| | Ahead-of-storm reserve | Predbat lists a "Weather Alert System" ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)). How it works was **not** read | None | **N21 (new)** | No |
| **Hot water** | The expected diversion modelled inside the plan, with a daily energy cap, a minimum SoC and gas price scaling | Predbat's iBoost model ([customisation](https://springfall2008.github.io/batpred/customisation/)) | Switching and temperature rules. The plan does not include it. Low value, because diversion starts only above a SoC threshold | S4 (evidence added) | No |
| | Variable-power diversion | Hardware diverters (iBoost, Eddi) | On and off only | Won't have (new row) | No |
| **EV** | Set the charge mode of more brands | Predbat starts and stops a Zappi, an Ohme and a GivEnergy charger ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)) | Finds five brands, sets the Zappi's mode only | **C31 (new)** | GivEnergy charger only |
| | Plan to a departure time | evcc ([roundup](https://diyai.io/ai-tools/engineering/best-ai-home-energy-management-tools/)); Predbat car plan ([car charging](https://springfall2008.github.io/batpred/car-charging/)) | None | N13 | No |
| | Import cap and session cap on the charger | GivTCP's GivEVC controls ([DATAPOINTS](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)) | None | Part of C31 | No |
| **Hardware** | All-In-One, gateway, three-phase, EMS, several inverters | GivTCP and givenergy-hass handle them. givenergy-hass publishes a validated and untested table ([README](https://github.com/dewet22/givenergy-hass)) | Tested on one hybrid | N3, N11 | Discovery and honesty, yes |
| | A local backend with no add-on and no MQTT broker | givenergy-hass (local Modbus) | GivTCP only | **N23 (new)**, C23 | Interface only |
| | Detect once, cache, offer a re-detect | givenergy-hass (`redetect_plant`) | Capacity read at setup | **C29 (new)** | No |
| | Read battery capacity live | GivTCP publishes `Battery_Capacity_kWh` and a module-based value | Read at setup | **C29 (new)** | No |
| | An action that exports an anonymised profile for support | givenergy-hass (`capture_frames`), givenergy-cli (`export`) ([PyPI](https://pypi.org/project/givenergy-cli/1.5.0/)) | A diagnostics download | **S19 (new)** | No |
| | Health counters (last refresh, failures, reconnects, dongle hangs) | givenergy-hass | Availability from entity states | New card in v0.19 | Yes: uses `Data_Age` |
| **Costs and savings** | Rates and standing charge read from a sensor | Predbat reads them from the Octopus Energy integration ([energy rates](https://springfall2008.github.io/batpred/energy-rates/)) | Typed in | N12 (evidence added) | No |
| | A savings ledger and payback run-rate | Energy Conductor, as described in the givenergy-hass README | ROI figures and a bill estimate | C5, N2 | No |
| **Interface** | A half-hourly plan table | Predbat's plan card ([docs](https://springfall2008.github.io/batpred/predbat-plan-card/)) | A sentence and a target | N14 | No |
| | Glance and wall-panel views | givenergy-hass (flow, glance, analyst, kiosk) | One tabbed dashboard | **N20 (new)** | No |
| | Per-module and per-cell battery health | givenergy-hass (cell heat map), GivTCP module and stack values | One state-of-health estimate | **N19 (new)**, N8, C17 | No |
| | Expose a recommended entity set to Assist and LLM tools | givenergy-hass (`expose_recommended_entities`) | None. Home Assistant does not expose power, energy or battery sensors by default ([thread](https://community.home-assistant.io/t/wth-are-all-new-entities-exposed-to-assist-by-default/803889)) | **C30 (new)** | No |
| **Safety and trust** | Warn when another controller sets the charge target | None found. givenergy-hass documents EMS plants reverting writes | The audit records only | S1 | Yes: conflict sensor and banner |

### B. Where this integration already matches or leads

| Capability | Note |
|---|---|
| Dry run before writing | Predbat has a read-only mode. Parity |
| Learned per-half-hour load, same weekday, newer days weighted | PALM uses previous days' consumption. Predbat weights by weekday and age. Parity or better |
| EV and immersion energy excluded from the learned house load | Verified in `core/engine.py` (`rest_of_house_w`). Predbat does the same with its car and iBoost sensors |
| Pessimistic forecast blend and accuracy correction | Predbat has comparable scaling. Parity |
| Day-after-tomorrow forecast lowers tonight's target | PALM's "overmorrow". Parity |
| Writes the window, target and enable switch as one sequence | PALM sets only the target. Users report confusion about the window |
| Bill-shaped cost tracking (VAT, levy, discount, projected bill) | Predbat adds a standing charge to plan costs. Not found: VAT, levy, supplier discount, bill period |
| Switch-based immersion control with temperature, ready-by times and second-heat-source advice | Predbat models a diverter and signals your automation. PALM has a temperature load sequencer for switched loads. A personal script boosts an immersion from battery charge through cloud APIs |
| A dashboard built from core cards, set up from the UI | Predbat is configured in a file and its example dashboards use custom cards |

### C. Things others do that are deliberately excluded here

Forced battery export and discharge (safety rule, and payment for export is the part most likely to be reduced). Multi-night planning on a fixed tariff. Cloud APIs. Optimisers and machine learning forecasters. PVOutput upload. Variable-power diversion.

### D. Problems others hit that this integration could share

| Problem | Seen in | Where it lands |
|---|---|---|
| A write to a child inverter (an All-In-One in a parallel setup) reads back correctly and changes nothing | GivEnergy's API documentation: child inverters "respond to commands but may not change their behaviour" ([API](https://givenergy.cloud/docs/api/v1)) | Test case SYS-25, and the gateway question U9 |
| A Gateway's inverter-shaped registers read as zeros, and it offers no controls | givenergy-hass | SYS-10, U9 |
| Solar energy counters on AC-coupled and All-In-One count battery output | givenergy-hass | SYS-06, SYS-08, U12 |
| An EMS plant reasserts settings, so writes revert within minutes | givenergy-hass troubleshooting | SYS-26, conflict sensor |
| The Gateway's battery power had the wrong sign before GivTCP 3.6 | GivTCP release notes ([3.6.0-beta1](https://github.com/britkat1980/giv_tcp/releases/tag/3.6.0-beta1)) | SYS-10, version policy |
| A failed poll republishes old values, so entities look healthy | GivTCP release notes | `Data_Age` check |
| A dongle that stops answering after a client changes behaviour | GivTCP issue [#614](https://github.com/britkat1980/giv_tcp/issues/614) | Retry limits and write caps |
| Gateway capacity and charge rate not populated | Predbat issue [#1427](https://github.com/springfall2008/batpred/issues/1427) | SYS-10 |

### E. Peers worth knowing

- **givenergy-hass** (dewet22) is a mature local alternative to GivTCP with a hardware capability model. [Repository](https://github.com/dewet22/givenergy-hass).
- **Energy Conductor** (same author, early days) is a technology-agnostic coordination layer with a plain-English plan, a cost ledger and a history and forecast tape. It overlaps with this integration's pitch. [Repository](https://github.com/dewet22/ha-energy-conductor). Not evaluated.
- **Predbat** is the established planner for dynamic tariffs. [Repository](https://github.com/springfall2008/batpred).
- **GivEnergy** itself moved cloud features, including Smart Tariff, behind a paid Premium tier. [FAQ](https://givenergy.cloud/givenergy-faq).


---

### F. Projects beyond GivEnergy

Searched in a second pass for ideas that apply here whatever the inverter. **Each row is a candidate for a specification (Part C (specifications) section 3).**

| Project | What it is | What it does that is relevant | What we could learn | Roadmap |
|---|---|---|---|---|
| [**PV Excess Control**](https://github.com/InventoCasa/PV-Excess-Control) | Surplus power and cheap tariff manager for Home Assistant | Three battery strategies (battery first, appliance first, balanced); minimum battery SoC protection; sheds appliances below a threshold; limits battery discharge while big loads run; absorbs would-be-curtailed export when a feed-in cap applies; allows a little grid power to top up a load; Tibber, Awattar, Nordpool and Octopus tariffs; savings, self-consumption ratio and energy statistics | Priority between battery, EV and immersion (C19), on and off smoothing (C18), cost and savings tracking (S17, N7) | C18, C19, S17 |
| [**EMHASS**](https://github.com/davidusb-geek/emhass) | Linear and mixed-integer programming energy manager with a machine-learning load forecaster and thermal models for water heaters | Day-ahead and model-predictive optimisation; treats a water tank as thermal storage; deferrable loads | The tank-as-storage idea for immersion sizing (N4). The optimiser itself is excluded as too heavy | N4, Won't have |
| [**evcc**](https://github.com/evcc-io/evcc) | EV charge manager with templates for hundreds of chargers, meters and inverters | Plans charging to a departure time using solar and dynamic prices; varies charge power on surplus and battery state; many vehicle integrations; notifications; its optimiser service is informational only so far ([docs](https://docs.evcc.io/en/features/optimizer.md)) | Departure planning (N13); charger templates (C31). A sign that even a mature project has not tried to control the home battery from an optimiser | N13, C31 |
| [**OpenEVSE integration**](https://github.com/firstof9/openevse) | Local control of OpenEVSE chargers | Solar divert mode; a claim and override system so several callers can queue, override or limit a charge | The claim model for arbitration (C19) | C19 |
| [**Octopus Energy integration**](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) | UK tariff, consumption and saving-session data | Target rate sensors (cheapest N hours between two times), cost trackers for any entity, three-rate tariff sensors for Cosy; the author is moving target rates into a separate source-neutral integration ([discussion](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/discussions/1305)) | Cheap-period sensors for the user's own automations (C34); cost tracking per entity (S17) | C34, S17 |
| [**Charge-battery**](https://github.com/mhurk/Charge-battery) | A small script that charges a home battery overnight only if tomorrow's solar will not cover the day, or the battery is nearly empty ahead of an expensive morning | The same two cases this integration's charge target covers, in a small form | Evidence of demand for the simple version. The empty-before-the-peak case is S5 | S5 |
| [**Solcast integration**](https://github.com/BJReplay/ha-solcast-solar) | The common forecast source | 30-minute and hourly detail attributes with 10, 50 and 90 percent values; dampening and hard limits; multi-site; **some attributes can be switched off** | The shape for FS (card FS1); the P10 attribute our code reads may be off | C32, N12 |
| [**Forecast.Solar (Home Assistant)**](https://www.home-assistant.io/actions/forecast_solar.get_forecast/) | Core forecast integration | An action returning `watts` and `wh_period` by period, raw or hourly | A second route to the shape | N12 |
| [**Open-Meteo Solar Forecast**](https://community.home-assistant.io/t/open-meteo-solar-forecast/733073) | Free forecast, no account | `watts` and `wh_period` attributes | A forecast source for people with no Solcast account | C33 |
| [**Helios Forecast**](https://github.com/ReikanYsora/Helios-Forecast) | Self-learning forecast from the user's own production, in the HACS default store | An action returning the full forecast; also lists a predicted battery state of charge | A learned forecast source. Overlaps with this integration's accuracy scaling | C33 |
| [**Smart immersion community project**](https://community.home-assistant.io/t/smart-immersion-heating-for-domestic-hot-water/536281) | Home Assistant automations for night immersion heating | Sizes the overnight top-up from tomorrow's forecast, adds outside-temperature compensation, heats to the maximum after a poor solar day, works from the tank's energy capacity | The forecast and weather rules in N4 and S4 | N4, S4 |
| [**T-Smart immersion thermostat**](https://github.com/andrew-codechimp/python-tsmart) | A smart replacement thermostat that reports the tank temperature and can switch the element | Gives the temperature and the control in one device, with no diverter | A hardware option to name in the immersion docs | Docs |

#### Considered and not added

| Idea | Seen in | Why not |
|---|---|---|
| Limit battery discharge rate while a large load runs | PV Excess Control | It writes a discharge setting. The write safety rules and the Won't have list exclude discharge and rate writes |
| Absorb would-be-curtailed export when a feed-in cap applies | PV Excess Control | Applies where an export cap exists. The existing divert rule already uses surplus. Revisit if a user with a cap asks |
| Demand flexibility and saving sessions | Octopus Energy integration, Predbat | Supplier-specific and UK-only. Not a fit for a tariff-agnostic integration without a design |
| Notifications through many services | evcc | Home Assistant already routes notifications. S6 covers a standing recommendations notification |
| Logging to InfluxDB and Grafana | evcc | Home Assistant statistics and the recorder cover it |
| Solar PV divert for the car at variable current | OpenEVSE, evcc | Needs a charger that accepts a current setting, and a write path the safety rules do not allow |


---

### G. Further projects found in the third pass

| Project | What it is | Seen | Read |
|---|---|---|---|
| [HAEO](https://github.com/hass-energy/haeo) | Linear programming optimiser as a native integration. Re-optimises on input change, multi-resolution horizon | About 70 stars. MIT | Its alternatives and horizon documents |
| [Akkudoktor EOS](https://github.com/akkudoktor-eos/eos) | Energy optimisation system. The next release adds 15-minute genetic plans, EV departure targets, flexible household loads and optional battery export | Active, no star count seen | README only |
| [BESS Manager](https://github.com/johanzander/bess-manager) | A Home Assistant add-on for price-optimised battery management with a wizard that discovers the inverter, price source and forecast | About 22 stars | README only |
| [solax-modbus](https://github.com/wills106/homeassistant-solax-modbus) | A widely used multi-brand local Modbus integration (Solax, some Solis, Growatt, Sofar) | About 500 stars on its topic page | Not read |
| [ha-solarman](https://github.com/davidrapan/ha-solarman) | Solarman stick logger integration for many inverters | About 500 stars | Not read |
| [solis_modbus](https://github.com/Pho3niX90/solis_modbus) | Solis local integration with work modes and time-of-use slots | About 160 stars | Not read |
| [Energy Flow Card Plus](https://github.com/flixlix/energy-flow-card-plus) and [Power Flow Card Plus](https://github.com/flixlix/power-flow-card-plus) | The most used flow cards. A listing shows Energy Flow Card Plus at about 270 stars | See source | Not read |
| Sunsynk Power Flow Card | A flow card used with several inverter integrations | Mentioned in several READMEs | Not read |

**Read in code this pass** (specifications in Part C): Predbat (load history and away mode, the diverter model), givenergy-modbus (detection, gating, quirks), the Target Timeframes integration (cheapest windows), PV Excess Control (allocation, shedding, battery protection), evcc's planner, and Helios Forecast's analog module (documentation and constants). **Not read in code:** Solcast, EMHASS, GivTCP, solax-modbus, ha-solarman, solis_modbus, the flow cards, EOS, BESS Manager. Star counts are as shown on the pages found and are a rough guide only.


