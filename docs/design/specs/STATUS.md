# Specification status and backlog

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


| Id | Topic | Status | Source | Feeds |
|---|---|---|---|---|
| SPEC-001 | PALM overnight charge target | **Extracted** (section 2, with vectors) | PALM `palm_utils.py`, `palm_soc.py` | S5, C24, C25, WS2 |
| SPEC-002 | Forecast interfaces: Solcast, Forecast.Solar, Open-Meteo | **Backlog.** Documentation read, not live instances. Card FS1 settles it | [Solcast README](https://github.com/BJReplay/ha-solcast-solar), [Forecast.Solar action](https://www.home-assistant.io/actions/forecast_solar.get_forecast/), [Open-Meteo thread](https://community.home-assistant.io/t/open-meteo-solar-forecast/733073). Solcast code not read | FS1, C32, C33 |
| SPEC-003 | Load history, weighting and away mode | **Extracted** (SPEC-003 below, with vectors) | Predbat `fetch.py`, `customisation.md` | C28, S5 |
| SPEC-004 | A diverter inside the plan | **Extracted** (SPEC-004 below) | Predbat `prediction.py`, `customisation.md` | S4, N4 |
| SPEC-005 | Hardware detection, caching and model gating | **Extracted** (SPEC-005 below) | givenergy-modbus `plant.py`, `inverter.py`, quirks doc | SY1, SY2, C29 |
| SPEC-006 | Cheapest-window selection | **Extracted** (SPEC-006 below, with vectors). Evaluation logic not read | Target Timeframes `entities/__init__.py` | C34, N13 |
| SPEC-007 | Surplus allocation, shedding and battery protection | **Extracted** (SPEC-007 below). Preempt and dynamic-current paths not read in detail | PV Excess Control `optimizer.py` | C18, C19, C20 |
| SPEC-008 | Departure-time plan | **Extracted** (SPEC-008 below). Continuous-window helper not read | evcc `core/planner/planner.go`, `planner.md` | N13 |
| SPEC-009 | Condition-matched forecast correction | **Partly extracted** (SPEC-009 below). Constants and confidence formula not read | Helios Forecast `analog.py` | N24 |
| NOTES | HAEO, EMHASS | **Approach notes only** (notes below) | HAEO docs | WS2 |
| SPEC-010 | Water heater thermal model | Backlog | [EMHASS](https://emhass.readthedocs.io/) docs and code | N4, S4 |
| SPEC-011 | GivTCP charge target behaviour | Backlog. Settings guide read, code not | GivTCP [settings guide](https://github.com/britkat1980/giv_tcp/blob/main/SETTINGS-GUIDE.md), code | U2, U8 |
| SPEC-012 | Control flags and child inverters | Backlog | [GivEnergy API](https://givenergy.cloud/docs/api/v1) | SY2, SYS-25 |
| SPEC-013 | Plan presentation | Backlog | [Predbat plan card](https://springfall2008.github.io/batpred/predbat-plan-card/) and `output.py` | N14 |
| SPEC-014 | Predbat's forward battery simulation (losses, rate curves, reserve, limits) | Backlog. The largest single source of modelling detail | Predbat `prediction.py`, `inverter.py` | C25 |
| SPEC-015 | Predbat's plan search and re-plan cadence | Backlog | Predbat `plan.py`, `execute.py` | WS2 |
| SPEC-016 | Entity model and discovery across many inverter brands | Backlog | `wills106/homeassistant-solax-modbus`, `davidrapan/ha-solarman` | SY, N23 |
| SPEC-017 | Price-optimising battery manager with setup discovery | Backlog | `johanzander/bess-manager` | wizard, N21 |
| SPEC-018 | Optimiser with EV departure targets and flexible loads | Backlog | Akkudoktor EOS | N13 |
| SPEC-019 | Energy flow and power flow cards | Backlog | `flixlix/power-flow-card-plus`, the Sunsynk power flow card | N20 |
| SPEC-020 | GivEnergy local Modbus entity set | Backlog | givenergy-hass entities and the service list | N23 |

**Rule for new specifications:** one file each in `docs/design/specs/`, using the template in section 1, written by the reader role, reviewed by the maintainer before any builder uses it. Work the backlog in the order shown, with SPEC-002 first because card FS1 needs it, then SPEC-014 and SPEC-015 for the plan.


---
