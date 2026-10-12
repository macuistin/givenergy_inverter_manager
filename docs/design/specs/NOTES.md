# Approach notes from other projects

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


#### HAEO (Home Assistant Energy Optimizer, MIT)
Read: its `docs/user-guide/alternatives.md` and `developer-guide/horizon-manager.md`.
- **Re-optimises when inputs change (debounced) and as the horizon advances**, instead of locking in a daily plan. It publishes a "now" setpoint plus forecast attributes. Our re-plan card (WS2) is a small version of the same idea with a hard cap on writes.
- **A multi-resolution horizon:** fine steps near the present and coarse steps far out (for example 1, 5, 30 and 60 minutes), so a multi-day look-ahead stays cheap. We plan one night in 30-minute steps, so we do not need it.
- **Linear programming first, integer variables as a last resort.** Out of scope, as recorded in the roadmap.
- **Provenance-aware pricing** (the same kWh is worth different amounts depending on whether it came from solar, grid or battery). A useful model for the cost split in our bill figures; no change proposed.
- **Its own comparison with EMHASS** says EMHASS suits day-ahead schedules and deferrable loads, and HAEO suits volatile prices. Neither targets a fixed time-of-use tariff with a single overnight decision, which is the case this integration serves.

#### EMHASS (not read in code)
Its documentation describes a water heater as thermal storage (a deferrable load with a thermal model). Not read beyond that.

#### Solcast, Forecast.Solar, Open-Meteo
Interfaces are summarised in the brief (card FS1). The code of the Solcast integration was not read.

#### GivTCP
Its settings guide and datapoints list were read earlier; its code was not.

#### Inverter integrations that are widely used but were not read
`wills106/homeassistant-solax-modbus` (about 500 stars on its topic page), `davidrapan/ha-solarman` (about 500), `Pho3niX90/solis_modbus` (about 160), the Huawei Solar integration, `johanzander/bess-manager` (about 20, a price-optimising battery manager with a setup wizard that discovers the inverter, price source and forecast), and the Akkudoktor EOS optimiser. They are queued in the backlog.


