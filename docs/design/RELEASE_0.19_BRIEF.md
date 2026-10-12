# Release 0.19: the brief

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

## Part A: The release brief (v0.19.0)

**For:** Claude Code, working in `macuistin/givenergy_inverter_manager`.
**Based on:** v0.18.0 (commit `461c5fc`, merge of PR #287).
**Release:** v0.19.0. Branches are `r019/<topic>`. Use `/release` to bump the version and write the changelog, and do it in the last card, not before. The removal of three sensor attributes (card RA1) is the one visible change, so say it plainly in the changelog.
**Read all of Part A before you write code.**

---

### 0. How to use this brief

1. This brief sits **below** the repository's own rules. Read `CLAUDE.md` (`AGENTS.md` is a symlink to it) and every file in `.claude/rules/` first: `home-assistant.md`, `core-purity.md`, `tests.md`, `safety.md`, `dashboard.md`, `python-style.md`, `docs-and-style.md`. If this brief and a rule file disagree, the rule file wins, **except** where section 15 says this release deliberately changes the rule. Then change the rule file in the same PR as the code. In any other disagreement, stop and say so.
2. The repository has three skills: `/add-sensor`, `/regenerate-goldens`, `/release`. Use them where a card says so.
3. **Do not guess.** Several cards depend on facts nobody has checked (section 3 lists them). Where a card says "verify", produce evidence first: a fixture, a test or a note in `docs/design/spikes/`. If a fixture is missing, stop that card and say what you need.
4. Cards are small. One card is one pull request unless the card says otherwise. PRs are stacked as `.claude/rules/docs-and-style.md` describes: each is based on the branch below it, merge commits, no rebase or amend on a branch with an open PR.
5. Say plainly which checks you ran. The three commands in `CLAUDE.md` (ruff, unit suite, end-to-end suite) run before every push. If you could not run the end-to-end suite, say so in the PR.

#### Your first actions

Part 0 of this document sets them. Follow Part 0.

---

### 1. Goal

Make the integration the single place where decisions are made, and GivTCP a **communication layer only**.

Concretely:

1. Put all GivTCP-specific code behind one small interface, so the rest of the integration never sees a GivTCP entity name.
2. Remove the comparison with GivTCP's own rates. Use those rates only as optional starting values on the setup tariff page.
3. Make the daily charge write more reliable: retry a missed write, and re-plan at sensible points before the cheap window closes.
4. Make the charge plan more accurate: use the forecast's own half-hourly shape, and make the seasonal rules configurable.
5. Warn on the dashboard when something else is setting the charge target (for example GivTCP's SmartTarget).
6. Support the GivEnergy EV charger through GivTCP.
7. Handle All-In-One, gateway and three-phase systems in discovery, as far as real evidence allows.
8. Housekeeping: README accuracy, progress notes, outstanding browser checks.

#### Out of scope. Do not start these.

- Talking to the inverter directly (Modbus) or a second backend such as givenergy-local. The interface in section 5 makes them possible later. Do not build them.
- Dynamic tariffs (Agile, Tibber) and any export or discharge logic. `.claude/rules/safety.md` forbids forced export.
- A second charge window (afternoon cheap rate). Some GivEnergy inverters have one charge slot only. (Designed in Part B section 3.4 for later.)
- Writing rates back into GivTCP.
- The sectioned-options storage, config migrations, entity renames or unit changes. Unique ids, entity ids and stored configuration stay as they are.
- A new dashboard layout. Keep the existing views.
- PVOutput upload and a load sequencer.

---

### 2. Decisions already made by the maintainer

| # | Decision |
|---|---|
| 1 | GivTCP stays the only backend. It becomes the communication layer only. |
| 2 | The integration owns the rates. GivTCP's rates are loaded as defaults on the setup tariff page only, never compared, never written back. |
| 3 | Remove the three Current Rate attributes `givtcp_rate_differences`, `givtcp_rates_differ` and `givtcp_rate_attributes`. The maintainer accepts the visible change. |
| 4 | Detect a competing charge controller first, then show the warning on the dashboard only when detected. |
| 5 | Retry a missed daily write. |
| 6 | Re-plan at relevant points before the cheap window ends (section 7, card WS2). |
| 7 | Use the forecast's half-hourly shape where the provider supplies it. |
| 8 | Seasonal rules become configurable. |
| 9 | Add GivEnergy EV charger support through GivTCP. |
| 10 | For All-In-One, gateway and three-phase discovery, learn from Predbat's documentation and code, from givenergy-hass and from GivTCP by the **specification-first method** (section 4, rule 16, and card SP0): read, write a specification in our own words, build from the specification. **Never copy code, comments, names or structure.** |
| 11 | Docs and user-facing text stay generic (`.claude/rules/docs-and-style.md`): no maintainer, no one household's bill. |

---

### 3. What is verified, and what is not

#### Verified in the repository at v0.18.0

| Fact | Where |
|---|---|
| `core/` imports nothing from `homeassistant`. A test enforces it. | `tests/test_metadata.py` |
| GivTCP-named identifiers are concentrated in `coordinator.py` (about 88 mentions), `discovery/givtcp.py` (31), `givtcp_writer.py` (24), `const.py` (21), `core/tariff_check.py` (16), `core/engine.py` (14), `repairs.py` (13), `wizard/wiring.py` (9). | search for `givtcp` |
| The daily write is one time listener, one minute before the cheapest rate period starts. `_register_charge_target_listener` registers it. `_charge_target_trigger` computes the time. `_write_charge_target_to_inverter` writes. | `coordinator.py` |
| The write sequence is: enable the charge schedule, set the window start, set the window end, set the target SoC, set the enable-charge-target switch. The switch goes OFF at 100% to avoid the charge-bounce bug. | docstring of `_write_charge_target_to_inverter` |
| A missed write (GivTCP or the inverter unavailable at the trigger time) is **not retried**. | `REQUIREMENTS.md`, "The write-back fires once per day" |
| The writer reads before writing, applies a cooldown and reads back. `GivTCPWriter` (`givtcp_writer.py`) exposes `set_switch`, `set_select`, `set_number` and `write_verified`. | `givtcp_writer.py` |
| The write audit records external changes (`EXTERNAL_REASON`, with `user_id` and `parent_id`) and **never reverts or raises a repair**. | `write_audit.py`, `.claude/rules/safety.md` |
| The GivTCP rate comparison is diagnostic only. The rates entered here always win. | `core/tariff_check.py` docstring |
| The solar curve is a fixed bell curve centred on 13:00, sigma 3.5 hours, between 06:30 and 19:30, 48 half-hour weights. | `_make_solar_slot_weights` in `core/rules.py` |
| The seasonal rules are constants: `CHARGE_WINTER_MONTHS = (12, 1, 2)`, `CHARGE_SHOULDER_MONTHS = (3, 4, 10, 11)`, `CHARGE_SHOULDER_MIN_SOC = 70`, `CHARGE_WINTER_SKIP_SOC_PCT = 95`. | `const.py`, used in `core/rules.py` |
| The code never reads a per-period forecast attribute (no `detailedForecast` anywhere). It reads a daily kWh total and, for Solcast, the `estimate10` attribute. | `coordinator.py` `_read_forecast_kwh`, `_read_p10_forecast` |
| EV chargers are found for five brands (`EVChargerBrand`: `ZAPPI`, `WALLBOX`, `OCPP`, `OHME`, `EASEE`, plus `GENERIC`). Only the Zappi has a charge mode select that the integration sets (`_apply_ev_action`, `_send_ev_mode`). The GivEnergy EV charger is not supported. | `discovery/ev_charger.py`, `coordinator.py` |
| There is no `binary_sensor.py`. The platforms are `sensor`, `number` and `switch`. | package listing |
| `RawSensorValues` in `core/engine.py` is the plain-values input to the engine. It holds inverter readings and also immersion and configuration fields. | `core/engine.py` |
| CI has a job for Home Assistant 2026.5.0 (the floor), which needs Python 3.14.2 or newer. | `.github/workflows/tests.yml`, `hacs.json` |

#### Not verified. Do not build on these until you have evidence.

| # | Open question | Evidence needed | Owner |
|---|---|---|---|
| U1 | **Answered from the GivTCP 3.6 documentation:** no entity reports SmartTarget or PALM. They are settings (`Smart_Target`, default off, with `PALM_*` settings). The conflict warning therefore uses behaviour. | Optional: one real entity list | Nobody needed |
| U2 | Does GivTCP apply a changed charge target **during** an open charge window? | A real test, or GivTCP source | Maintainer on the test instance |
| U3 | Which per-period data do the Solcast, Forecast.Solar and Open-Meteo Solar Forecast integrations expose for tomorrow, through which interface (state attributes, a provider action, or Home Assistant's solar-forecast platform), and in what units and time zone? Documentation says: Solcast `detailedForecast` has 30-minute periods with `period_start`, `pv_estimate`, `pv_estimate10` and `pv_estimate90`, and some attributes can be switched off; Forecast.Solar has an action `forecast_solar.get_forecast` returning `watts` and `wh_period`; Open-Meteo has `watts` and `wh_period` attributes. **None of this is verified against a live instance.** | Fixtures from real instances | Maintainer, then you |
| U4 | **Mostly answered.** GivTCP 3.6 documents the charger entities: `Charging_State`, `Connection_Status`, `Plug_and_Go`, `Charge_Control` (`Start`, `Stop`), `Charging_Mode` (`Grid`, `Solar`, `Hybrid`), `Charge_Limit`, `Import_Cap`, `Max_Session_Energy`. **Still unknown:** the exact state strings and the entity ids on a real system. | An anonymised entity list from a charger owner | Maintainer |
| U5 | What are the entity names and prefixes on All-In-One, gateway, three-phase and second-inverter systems? | Anonymised entity lists | Maintainer |
| U6 | **Answered from the GivTCP 3.6 source.** Its shipped default settings hold `day_rate` 0.395, `night_rate` 0.155, `export_rate` 0.04, day rate start 05:30 and night rate start 23:30. A user who never entered rates therefore reads those values, not zero. | Done | Nobody needed |
| U7 | Do the Spike SP2 frontend checks pass (Community dashboards entry, `getCreateSuggestions`, Take control, distribution card)? | A browser | Maintainer |
| U8 | **Partly answered.** `Enable_Charge_Target` on means charging stops at `Target_SOC`; off means charge to 100 percent. Per-slot targets (`Charge_Target_SOC_N`) exist on 10-slot inverters, three-phase and the Gateway. GivTCP 3.6 fixed a bug where Force Charge did nothing on 10-slot inverters when the SOC was above slot 1's target, which suggests slot 1's target matters there. **Still unknown:** whether `Target_SOC` alone governs a charge on those inverters. | A real charge on such an inverter | Maintainer or a fixture owner |
| U9 | **Mostly answered.** In GivTCP 3.6 the Gateway's controls that failed now work, and it has charge and discharge rates and per-slot target SOCs. It publishes whole-house power values and, per All-in-One, SOC, power and AC energy. **Still unknown:** which entity is the right one to write a charge schedule to on a parallel All-in-One system, and whether a write there changes behaviour. | A Gateway entity list and one real charge | Maintainer |
| U10 | **Answered from the 3.6 datapoints list:** `Invertor_Type`, `GivTCP_Version`, `Data_Age`, `status` (`online` or `paused`), `Time_Since_Last_Update` and `Invertor_Time` are **sensors**. **Still unknown:** the exact `Invertor_Type` strings. | An entity list from 3.6 | Maintainer |
| U11 | Which GivTCP versions do we support? **GivTCP 3.6 was released on 11 October 2026, with 3.6.1 four hours later and 3.6.2 about 35 minutes after that.** Recommend 3.6.2 as the floor within 3.6, because 3.6 and 3.6.1 reset entity ids and mis-handle slot 2 and PV-only inverters. **GivTCP 3.6 final was released on 11 October 2026**, and upgrading from 3.5 changes entity sets and one set of units (Appendix D.7). Users will move over the coming weeks, so 3.5 and 3.6 will both be in use. | A decision, and fixtures at both versions | Maintainer |
| U12 | GivTCP 3.6 says AC-coupled and All-in-One models can only measure the **total from the PV inverter**, so `PV_Power` is that total. **Still unknown:** whether the solar **energy** counters on those models count solar or the unit's battery-discharge AC output, as another integration reports. | An AC or All-in-One fixture, compared with a known solar meter | Maintainer or a fixture owner |

---

### 4. Guardrails (non-negotiable)

These come from the repository rules. They are listed here because several cards touch them.

1. **Dry run.** Every write to the inverter, the immersion switch and the EV charger checks `coordinator.is_dry_run` first. In dry run it records `Would ...` through `_record_skipped`, logs a `DRY RUN:` line and sends nothing. **Every new write path in this release (retry, re-plan, EV mode) needs a test that sets dry run and asserts nothing was sent.** Never read `CONF_DRY_RUN` from the entry in new code.
2. **No forced export or discharge.** Write no export or discharge schedule, rate or reserve.
3. **Never stop or pause an EV charger.** For a Zappi, select Eco+ and never Stopped or Fast. The GivEnergy charger gets the same rule (card GE2).
4. **Writes go through the writer.** Read before write, cooldown, read back. Do not call a GivTCP service from anywhere else.
5. **The write audit only records.** It never reverts and never raises a repair. Card CC does not change that.
6. **`core/` stays pure.** No `homeassistant` imports, no wall clock (pass `now`), no files, no network.
7. **Golden files are checks, not records.** A refactor card must leave them unchanged except for fields it removes or renames. Behaviour cards change them on purpose, through `/regenerate-goldens`, and the PR shows the diff and explains each change.
8. **Entity ids, unique ids and keys never change.** `tests/ha_e2e/test_entity_snapshot.py` pins them. The only removals in this release are three attributes (card RA1).
9. **No new option, constant or entity without searching `const.py` for one to reuse.** Say so in the PR when you add one. A new option key is `LIVE_KEYS` or `RELOAD_KEYS` in `core/reload_policy.py`, and `tests/core/test_reload_policy.py` needs its row.
10. **Optional devices may be absent or added later.** The EV charger, the immersion switch and the immersion sensor each need a with-and-without test.
11. **Docs are generic.** UK English. No maintainer, no personal names, no serial numbers in docs, README, changelog or user-facing strings.
12. **Never weaken a test to get green.** No deletion, no looser assertion, no `skip`, no `xfail` for a failure you caused.
13. **Do not add source-grep tests** (read a file, assert a string). Test behaviour.
14. **Commits:** Conventional Commits. No `Co-Authored-By` line, no "Generated with" line.
15. **Rules change with the code.** If a card makes a sentence in `CLAUDE.md`, a rule file or a skill untrue, change that file in the same PR (section 15). List it under "Rules changed" in the PR body. `CLAUDE.md` stays under 150 lines (a test enforces it). Put detail in a rule file.
16. **Specification first.** Other projects are studied, not copied. A reader writes a specification in our own words (behaviour, formulas, constants, failure behaviour, test vectors, and no code); a builder implements from the specification with the other project's source closed; a checker compares our output with the vectors and reports differences as questions.  Part C (specifications) section 1 is the method and `docs/design/specs/` holds the specifications.

---

### 5. Target architecture: the inverter backend

#### 5.1 The idea

Today the coordinator knows GivTCP's entity names, reads their states, builds `RawSensorValues` and runs the write sequence. After this release the coordinator talks to an `InverterBackend` with a short list of jobs. A GivTCP adapter does the jobs. Nothing outside the adapter mentions GivTCP in code.

User-facing text may still say "GivTCP", because it is the thing the user installed. Repair texts, docs and the wizard keep saying it.

#### 5.2 Package layout (proposed. Adjust if the code says otherwise, and tell the maintainer)

```
custom_components/givenergy_inverter_manager/
  core/
    inverter_values.py        pure frozen dataclasses: InverterValues, ChargePlan, RateDefaults
  inverter/
    __init__.py
    backend.py                the InverterBackend Protocol (no homeassistant import)
    givtcp/
      __init__.py             make_backend(hass, cfg) -> InverterBackend
      discovery.py            moved from discovery/givtcp.py
      writer.py               moved from givtcp_writer.py
      sequence.py             the write sequences moved out of coordinator.py
      constants.py            the GIVTCP_* constants moved out of const.py
tests/
  fakes/fake_inverter.py      a backend that implements only the interface
```

Keep `tools/mock_givtcp.py`. It becomes the test double for the GivTCP adapter in the end-to-end suite.

`core/` may import `core/inverter_values.py`. It must not import `inverter/`. `tests/test_metadata.py` must stay green.

#### 5.3 The interface (illustrative names)

| Job | Meaning | Today it lives in |
|---|---|---|
| `identity` | Serial, kind of system, entity-name prefix | `GivTCPInverter` (`discovery/givtcp.py`) |
| `read(cfg) -> InverterValues` | Solar power, battery SoC, battery power, grid power, house load, battery capacity, the daily energy counters, the charge rate in watts, the age of the data (`Data_Age`, where GivTCP publishes it), and the names of anything unreadable | `_collect_raw`, `_read_power_inputs`, `_read_daily_counters`, `_read_charge_rate_w`, `_read_tracked` in `coordinator.py` |
| `is_publishing()` and `note_publishing()` | Is GivTCP alive and fresh | `_require_givtcp_publishing`, `_note_givtcp_publishing`, `_note_givtcp_silent`, `_givtcp_was_unavailable` |
| `apply_charge_plan(plan) -> WriteResult` | Enable the schedule, set the window, set the target, set the enable-charge-target switch (OFF at 100%) | `_write_overnight_target`, `_async_apply_charge_target`, `_write_charge_window` |
| `apply_minimum_target(soc)` | The skip-charge write | `_write_minimum_target` |
| `apply_floor_target(soc)` | The cheap-rate floor top-up | `_write_floor_target` |
| `other_active_charge_slots()` and `clear_charge_slot(slot)` | Slots set by something else | `_other_charge_slots`, `_check_other_charge_slots`, `_clear_charge_slot` |
| `read_rate_defaults() -> RateDefaults or None` | Day, night and export rate, only for the setup tariff page (card RA2) | new |
| `watched_entity_ids()` | The entities the write audit watches | the list built in `coordinator.py` |

#### 5.4 Rules for the refactor cards (IB1 to IB7)

- **No behaviour change.** The unit suite, the end-to-end suite and every golden file must pass unchanged. The only golden change allowed in IB cards is the removal or rename of a field the card removes or renames.
- **The coordinator keeps the dry-run check.** Decide where it lives, then test that nothing is sent in dry run. `immersion_actuator.py` already takes `is_dry_run` as a port. Follow that pattern.
- **Sign conventions stay in the adapter.** GivTCP's grid and battery signs are negated on read (`_collect_raw`). After the refactor, the adapter does the negation and `InverterValues` uses the integration's convention (grid positive is import, battery positive is charging). The two tests named in `CLAUDE.md` (`test_reads_grid_power_negative_when_exporting`, `test_reads_battery_power_discharging`) must still pass, and their meaning must not weaken.
- **GivTCP daily counters** (`_apply_daily_counters` in `core/engine.py`) stay an input. Rename the comments to "inverter counters".
- **Do not change** the repair issue id `ISSUE_GIVTCP_ENTITIES_MISSING`, `_RETIRED_*` lists, unique ids, config keys or the stored configuration.
- Search for every identifier you rename. The full list is in the appendix.

---

### 6. Cards: inverter backend (IB) and rates (RA)

Sizes: S (under half a day), M (about a day), L (more). Estimates are for human coding. They mean little for you. Review and the checks are the cost.

#### IB1. Define the interface and the pure types. Size S

**Goal:** the contract exists, with nothing using it yet.
**Work:**
- Create `core/inverter_values.py` with frozen dataclasses `InverterValues`, `ChargePlan` (target percentage, window start and end, whether the enable-charge-target switch is wanted) and `RateDefaults`.
- Create `inverter/backend.py` with the `InverterBackend` Protocol (section 5.3).
- Derive the exact field list of `InverterValues` from what `_collect_raw` and its helpers read today. Do not invent fields. List them in the PR.
**Tests:** a unit test builds each dataclass and checks it is frozen. `tests/fakes/fake_inverter.py` implements the Protocol, and a test type-checks that.
**Done when:** `ruff` is clean, the suites are green, no existing behaviour changed.

#### IB2. Move discovery into the adapter. Size M

**Goal:** `discover_givtcp_inverters`, `GivTCPInverter`, `get_suggested_entities`, `inverter_temperature_entity_ids`, `find_other_active_charge_slots`, `ActiveChargeSlot`, `describe_charge_slots` and `discover_battery_cycle_entities` move to `inverter/givtcp/discovery.py`. Keep `GIVTCP_PREFIX` with them.
**Work:** move, fix imports in `discovery/__init__.py`, `wizard/wiring.py`, `wizard/setup_flow.py`, `coordinator.py`, `repairs.py`. Leave `discovery/ev_charger.py` and `discovery/forecast.py` where they are.
**Not in this card:** `givtcp_rate_entity_ids` (card RA1 removes it).
**Tests:** the existing `tests/discovery/test_givtcp.py` moves with the code and passes unchanged.
**Done when:** wizard forms are identical (`tests/ha_e2e/golden/config_flow_forms.json` unchanged).

#### IB3. Move the writer. Size M

**Goal:** `givtcp_writer.py` becomes `inverter/givtcp/writer.py`.
**Work:** move `GivTCPWriter`, `VerifiedWrite`, the write-record helpers and the constants `GIVTCP_MIN_WRITE_INTERVAL_S`, `GIVTCP_MAX_WRITE_RETRIES`, `GIVTCP_WRITE_RETRY_SLEEP_S`, `GIVTCP_WRITE_LIFETIME_WARN`, `GIVTCP_MIN_CHARGE_TARGET_PCT`, `GIVTCP_MAX_CHARGE_TARGET_PCT` into `inverter/givtcp/constants.py`. Keep the names.
**Watch for:** `write_audit.py` imports `GIVTCP_MIN_WRITE_INTERVAL_S` from `const.py`. Re-point it. The audit stays a recorder.
**Tests:** every existing writer test passes unchanged. `tests/ha_e2e/test_write_sequence_e2e.py` passes.

#### IB4. Move the write sequences out of the coordinator. Size L

**Goal:** the coordinator calls `backend.apply_charge_plan(...)`, `apply_minimum_target(...)`, `apply_floor_target(...)` and `clear_charge_slot(...)`. The five-step sequence lives in `inverter/givtcp/sequence.py`.
**Work:** move `_write_overnight_target`, `_write_minimum_target`, `_async_apply_charge_target`, `_write_charge_window`, `_write_floor_target`, `_clear_charge_slot` and the helpers they use. The coordinator keeps the time listener, the dry-run check, `_record_skipped`, and the choice of **what** to write. The adapter owns **how**.
**Watch for:**
- The enable-charge-target rule (OFF at 100%, ON below) moves with the sequence and keeps its comment.
- Counting register writes (`_save_register_write_count`, `self._writer.write_count`) must still work.
- `_held_charge.release()` stays in the coordinator.
- **Move the sequence exactly as it is.** U8 asks whether `Target_SOC` with `Enable_Charge_Target` stops a charge on inverters with per-slot targets. If the answer is no, the sequence needs a change. That change is its **own card after IB4**, not a quiet edit inside the move.
**Tests:**
- `tests/ha_e2e/test_write_sequence_e2e.py` passes unchanged, using `tools/mock_givtcp.py`.
- Add a test against `tests/fakes/fake_inverter.py` that the coordinator calls the backend once with the expected plan.
- Dry-run test: with `dry_run` on, the fake backend receives no write.
**Done when:** the coordinator contains no `givtcp` entity-name string. Search before you finish.

#### IB5. Move reading and availability. Size M

**Goal:** `_collect_raw` builds `RawSensorValues` from `backend.read(cfg)` plus the non-inverter fields it already sets (immersion, EV, forecast, tariff).
**Work:** move the inverter reads and the sign negation into the adapter. Move `_require_givtcp_publishing`, `_note_givtcp_publishing`, `_note_givtcp_silent` and `_givtcp_was_unavailable` behind `is_publishing()` and `note_publishing()`.
**Staleness:** when a poll fails, GivTCP 3.6 and later **republishes the last good data**, so entities stay available but old. It publishes `Data_Age` (seconds, `-1` if nothing has been read) to say so. `is_publishing()` must treat a large `Data_Age` as not publishing, so no write goes out on old numbers. Choose the threshold with the maintainer (start with three times the poll interval). GivTCP 3.6 also publishes `status` (`online` or `paused`) and `Time_Since_Last_Update` as sensors. **Treat `paused` as not publishing** (GivTCP stops sending to a struggling inverter on purpose, and drops writes while paused). Where `Data_Age` does not exist (older GivTCP), say that staleness cannot be detected. Do not guess. U10 is answered: these are sensors.
**Watch for:** the repair `ISSUE_GIVTCP_ENTITIES_MISSING` and its create and delete helpers keep their ids and their text.
**Tests:** `tests/test_coordinator.py` (including the two sign tests) passes. Add a contract test that runs the same read assertions against the GivTCP adapter (with the mock) and the fake backend.

#### IB6. Neutral names in `core/` and in comments. Size S

**Goal:** `core/` no longer says "GivTCP" in identifiers or comments, except where the sentence is about the user-visible product.
**Work:** in `core/engine.py` change comments such as "GivTCP daily energy counters" to "inverter counters". The only identifier to rename is the rate comparison field, and card RA1 deletes it, so do RA1 first or together.
**Tests:** golden files unchanged.

#### IB7. Contract tests and a second fake. Size M

**Goal:** a shared test class that any backend must pass.
**Work:** `tests/backend_contract.py` with tests for `read`, `is_publishing`, `apply_charge_plan` (including the 100% case), dry run, and failure handling. Run it against the GivTCP adapter (with the mock) and against `fake_inverter.py`.
**Why:** the next backend, if there ever is one, starts from a passing contract.
**Done when:** both implementations pass. `docs/design/mock_givtcp.md` and `docs/architecture.mermaid` describe the new layer.

---

#### RA1. Remove the GivTCP rate comparison. Size M

**Goal:** the integration owns the rates. It no longer compares them with GivTCP's.
**Delete or remove:**
- `core/tariff_check.py` (`GivTCPRates`, `RateMismatch`, the comparison) and `tests/core/test_tariff_check.py`.
- The `givtcp_rate_mismatches` field in `core/engine.py` and its use.
- In `coordinator.py`: `_read_givtcp_rates`, `_compare_givtcp_rates` and their call sites.
- In `sensor_values.py`, `sensor_descriptions/tariff.py` and `sensor.py`: the three Current Rate attributes `givtcp_rate_differences`, `givtcp_rates_differ`, `givtcp_rate_attributes`.
- In `const.py`: `GIVTCP_RATE_SUFFIXES` and `GIVTCP_RATE_TOLERANCE_PCT`. Keep the suffix list long enough to feed RA2, then move it into the adapter.
- In `discovery/givtcp.py`: `givtcp_rate_entity_ids` (RA2 replaces it with the adapter method).
- Tests: `tests/test_givtcp_rates_attribute.py`, `tests/ha_e2e/test_givtcp_rates_attribute_e2e.py`, and the related lines in `tests/test_unrecorded_attributes.py`, `tests/test_sensor_values.py` and `tests/discovery/test_givtcp.py`.
- Docs: `docs/tariff.md` and `docs/sensors.md` (regenerate the table with `scripts/gen_sensor_docs.py`).
**Golden files:** `tests/core/golden_engine_snapshots.json` changes **only** by losing the removed field. Use `/regenerate-goldens` and show in the PR that no other value moved.
**Keep:** the rule that the rates entered here win, dated rate changes, and the "confirm the tariff is current" reminder.
**Changelog:** list the three attributes under "Removed".

#### RA2. Rate defaults on the setup tariff page. Size M

**Goal:** when GivTCP holds rates, the setup tariff page starts from them. After setup, rates are managed only in Configure.
**Work:**
- Implement `read_rate_defaults()` on the GivTCP adapter. It returns the day, night and export rate it can read (GivTCP's `Day_Rate`, `Night_Rate` and `Export_Rate` datapoints, set on its config page), or nothing. GivTCP counts its money values in pounds per kWh. Do not convert, and do not assume the user's currency.
- The setup flow (`wizard/setup_flow.py` and `core/wizard_tariff.py`, see `default_rate_rows`) pre-fills the base rate with the day rate and the export rate with the export rate. The night rate becomes the rate of the first time-of-day row. Do not invent the night window.
- **Pre-fill only a value that is readable, greater than zero and not one of GivTCP's shipped defaults.** GivTCP holds day 0.395, night 0.155 and export 0.04 until the user changes them (U6), so those exact values mean "never set". If all three equal the defaults, pre-fill nothing. Do not take the rate start times either (05:30 and 23:30 are defaults). Everything else stays empty, as 0.18 set it up ("no placeholder prices").
- Show a line on the page: "Taken from GivTCP. Check them against your bill."
- Nothing is stored before the confirm screen, as today.
**Verify first (U6):** what GivTCP holds on an install where the user never entered rates. If it holds a default such as 0.155, the pre-fill would look authoritative and be wrong. Decide with the maintainer: compare against the known default and skip, or show a stronger warning. Do not guess.
**Tests:**
- Core test: the pre-fill function, with readable, zero, missing and negative values.
- End-to-end: the setup form with and without GivTCP rates. This changes `tests/ha_e2e/golden/config_flow_forms.json`. Regenerate it on purpose and explain each change.
- The Configure tariff page does not read GivTCP's rates.
**Docs:** `docs/configuration.md` setup section and `docs/quick-start.md`.

#### RA3. Changelog and docs for the rates change. Size S

**Work:** `CHANGELOG.md` entry (Removed: the three attributes; Changed: the setup tariff page can start from GivTCP's rates). `docs/tariff.md` no longer mentions comparing rates.

---

### 7. Cards: write reliability (WS) and the competing-controller warning (CC)

#### WS1. Retry a missed daily write. Size M

**Goal:** if the write at the trigger time fails or cannot be sent, try again inside the cheap window instead of losing the night.
**Today:** `_write_charge_target_to_inverter` runs once, one minute before the cheapest period starts. `REQUIREMENTS.md` says a missed write "is not retried".
**Design:**
1. A write has **failed** when the backend is not publishing, or `apply_charge_plan` returns not-ok after the writer's own retries. A read-before-write that finds the values already correct is a success.
2. On failure, schedule retries at **+2, +5, +10 and +20 minutes** after the trigger. Stop when less than **15 minutes** of the window remain. Constants: `CHARGE_WRITE_RETRY_OFFSETS_MIN` and `CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN`. Search `const.py` first.
3. Reuse the window maths in `core/charge_window.py` (`ChargeWindow`, `cheapest_period`) and the tariff helpers (`get_cheapest_rate_start`). Read them first. Do not write new window arithmetic.
4. One pending retry at a time. Callbacks are `@callback` functions. Cancel them on unload and when the window ends.
5. **Catch-up after a restart.** On setup, if now is inside the window (after the trigger, at least 15 minutes before the end) and the write log shows no manager write to the charge target since the trigger, do the write. Decide "already written tonight" from the write log (`core/write_log.py`), as a pure function. **Do not add a stored field**, so the accumulation store keeps its shape.
6. **Dry run:** record one `Would write ...` entry per night, not one per retry.
7. Each retry that sends counts in the register write count and obeys `GIVTCP_MIN_WRITE_INTERVAL_S`.
**Tests (all with a controlled clock):**
- backend unavailable at the trigger, available at +5: one write at +5.
- fails four times: stops, and the last write log entry says so.
- success at the trigger: no retry is scheduled.
- restart at trigger +30 minutes with no write logged: one catch-up write.
- restart after the window ends: nothing.
- dry run: one `Would write` entry, nothing sent.
- a manual override is set: the retry writes the override, not the calculated target.
- flat-rate tariff: no listener, no retry.
**Docs:** `REQUIREMENTS.md` ("The write-back fires once per day"), `docs/concepts.md`, `docs/troubleshooting.md`.

#### WS2. Re-plan inside the cheap window. Size L

**Goal:** if the forecast or the situation changes after the first write, correct the target before the window closes. Predbat and GivTCP's PALM both do something similar. Reimplement the idea from this specification only.
**Triggers (all evaluated only while the window is open and at least 15 minutes remain):**
1. **Late check:** at `max(trigger + 30 minutes, window end - 60 minutes)`.
2. **Forecast change:** the forecast used for the plan differs from the one used for the last write by at least 15% and at least 1 kWh.
3. **EV change:** an EV charger is plugged in or unplugged (the engine adds 10 points when one is plugged in).
**Rules:**
- Write only if the new target differs from the last written target by **at least 5 points** (`REPLAN_MIN_CHANGE_PTS`).
- At most **3 re-plan writes per night** (`REPLAN_MAX_WRITES`). With the first write that is 4 target writes at most.
- Never write outside the window. Never open a window.
- A manual override disables re-planning for that night.
- The cap (default overnight charge target) and the minimum-SoC floor apply as they do to the first write. A new target below the current SoC is allowed. Charging simply stops.
- Dry run: record `Would re-plan ...` once per trigger. Send nothing.
- Use the same backend call and the same writer. Counts and cooldowns apply.
**Design:** a pure function in `core/replan.py`, `decide_replan(inputs) -> ReplanDecision(write, target, reason)`, with a frozen `ReplanInputs` (now, window start and end, last written target and forecast, new target and forecast, EV plugged before and now, re-plans so far, override active). The coordinator gathers the inputs and acts on the result. `calculate_overnight_charge_target` does not change, so its golden files stay unchanged.
**Reason text:** the Overnight Charge Reason sensor says what happened: "Re-planned at 03:00: the forecast fell by 20%." Keep it under the state limit (`fit_state`).
**Verify U2 before you enable it.** If nobody can confirm that GivTCP applies a changed target during an open window, ship with re-planning off by default behind a switch control (`controls.py`, `LIVE_KEYS`) and tell the maintainer. If U2 is confirmed, do not add a control.
**Tests:**
- Table tests for `decide_replan`: each trigger, every threshold at, below and above, the cap, an override, outside the window, dry run.
- Coordinator test with `fake_inverter.py` and a controlled clock.
- End-to-end test with `tools/mock_givtcp.py`: target changes mid-window and the written values are correct, including the 100% case (enable-charge-target OFF).
- Existing golden files for the charge target stay unchanged.
**Docs:** `docs/concepts.md` gets a "Re-planning" subsection under "Overnight charge target". Changelog entry.

#### WS3. Make retries and re-plans visible. Size S

**Work:** write log entries carry the reasons `retry` and `replan` (see `core/write_log.py`). The register write count sensor attribute already shows the log. Do not add a new sensor.
**Tests:** the log shows each kind once, in order, and `tests/test_state_length.py` still passes.

---

#### CC1. Spike: can we read whether SmartTarget is on? Size S

**Goal:** answer U1 with evidence.
**Status (GivTCP 3.6, 11 October 2026):** its datapoints list has no SmartTarget or PALM entity. They are settings (`Smart_Target`, default off). Treat the answer as "no entity" and **start CC2 on behaviour now**. Confirm on a real entity list when one arrives; this does not block.
**Work:** with the maintainer's entity list from a real GivTCP (Developer Tools, States, search "smart" and "palm"), record whether any entity reports SmartTarget or PALM. Write `docs/design/spikes/CC1.md`.
**Outcomes:**
- An entity exists: CC2 reads it. The banner can say "SmartTarget is on" exactly.
- No entity: CC2 uses behaviour (below) and the banner says "something else".
**Do not** call GivTCP's REST interface. That would add an address setting.
**Version note:** GivTCP 3.6.0-beta1 fixed a bug where the Smart Target setting "was ignored and followed the Dynamic Tariff setting instead". Older versions may behave oddly.

#### CC2. Detect another controller. Size M

**Goal:** a pure function says whether something other than this integration is changing the charge target.
**Work:** `core/controller_conflict.py`. Input: the write log entries for the charge target entity (`core/write_log.py`) and `now`. Output: a frozen `ConflictStatus(state, count, last_seen_iso, entity_id)` with `state` either `none` or `suspected`.
**Rule:** count entries whose reason is `EXTERNAL_REASON` and whose `user_id` is empty. The audit already ignores the echo of our own writes (`is_echo`). **Suspected** when there are at least 2 such changes in the last 3 days (`CONFLICT_MIN_CHANGES`, `CONFLICT_WINDOW_DAYS`). It clears after 3 days without one.
**Known false positives:** a change made in the GivEnergy app reaches GivTCP with no Home Assistant user. An EMS plant also reasserts settings itself (SYS-26). The wording must say "something else", never claim it is PALM.
**Tests:** table tests: none, one change, two changes, changes with a `user_id`, our own echo, ageing out.
**Rule check:** this reads the log. It never reverts a change and never raises a repair (`safety.md`).

#### CC3. The sensor, the banner and the docs. Size M

**Work (use `/add-sensor`):**
- A diagnostic sensor **Charge Target Conflict** (`entity_category = diagnostic`, enum states `none` and `suspected`, attributes `count`, `last_seen`, `entity_id`). Do not add a platform: the integration has no `binary_sensor.py`.
- A banner on the dashboard next to the dry-run banner (find it by searching `test_instance` in `dashboard/views.py`). Use a `conditional` card with a plain `state` condition on that sensor. The floor is Home Assistant 2026.5, so **do not use the newer visibility condition types** (2026.10).
- Banner text: "**Something else is setting your charge target.** This integration saw the target change without a write from it. Common causes are GivTCP's SmartTarget, Predbat or the app. Turn that off so only this integration sets the target. This message clears after three days without a change."
- `tests/golden_dashboard_matrix.json` changes. Regenerate it with the skill and show the diff.
- `tests/ha_e2e/test_entity_snapshot.py` gains the new entity on purpose.
- `docs/dashboard.md`, `docs/troubleshooting.md`, and one line in `docs/quick-start.md`: "Leave GivTCP's SmartTarget off."
**Done when:** a test drives two external target changes and the sensor flips to `suspected`, and the banner appears in the dashboard output for that state only.

---

### 8. Cards: forecast shape (FS) and seasonal rules (SR)

#### FS1. Spike: what do the forecast providers give us? Size M

**Goal:** answer U3 with fixtures. **Do not assume attribute names.**
**Three interfaces to test, in this order of preference** (from the provider documentation, not yet verified on a live instance):
1. **Home Assistant's own solar-forecast platform** (the source the Energy dashboard uses), which gives a timestamped Wh-per-period profile (`wh_hours`) for any provider that supports it. Another project reads it this way for Forecast.Solar and Solcast. One interface for every provider is the best outcome. Check how a custom integration can read it and which Home Assistant versions allow it.
2. **A provider action.** Forecast.Solar has `forecast_solar.get_forecast`, which returns `watts` and `wh_period` mappings keyed by period start with a time zone, as `raw` or `hourly` periods ([documentation](https://www.home-assistant.io/actions/forecast_solar.get_forecast/)). Calling it needs a config entry id and a response.
3. **Sensor attributes.** Solcast's `detailedForecast` (30-minute periods with `period_start`, `pv_estimate`, `pv_estimate10`, `pv_estimate90`) and an hourly breakdown ([README](https://github.com/BJReplay/ha-solcast-solar)). Open-Meteo Solar Forecast has `watts` and `wh_period` attributes. **Solcast lets users switch some attributes off** (options such as `attr_brk_estimate10` and `attr_brk_hourly`), so a missing attribute must be handled, and the P10 read in `coordinator.py` depends on one of them.
For each provider and each interface, document in `docs/design/spikes/FS1.md`: where tomorrow's per-period energy is exposed, the period length, the units (energy or average power; one source disagrees on this for Solcast), the time zone, and when it updates. Record which attributes are on by default. Add anonymised fixtures under `tests/fixtures/forecast/`. Say what each provider holds between midnight and 08:00, because the code uses the forecast it remembered just before midnight for that period (`docs/concepts.md`, step 3 of the overnight target).
**Output:** a table, and a decision: which providers can give a shape and which cannot.
**If only totals are available** for a provider, that provider keeps the standard curve. That is acceptable.
**Also record:** whether Solcast's `estimate10` attribute is on by default, and what the integration does today when it is off. If it silently has no effect, say so, because a roadmap item (C32) covers telling the user.

#### FS2. Use the shape in the simulation. Size L

**Goal:** the 48-slot simulation uses the forecast's own shape when one is available. Otherwise it uses today's bell curve.
**Work:**
- `core/solar_day.py` is the likely home (read it first). Add a validated `solar_shape_from_periods(periods, tz) -> tuple[float, ...] | None`: 48 non-negative finite weights in local half-hour slots, summing to 1. Return `None` for anything invalid.
- Add `solar_shape: tuple[float, ...] | None = None` to `ChargeInputs`. `_simulated_plan` uses it when valid, else `_SOLAR_SLOT_WEIGHTS`.
- The coordinator reads the shape beside the daily total and remembers the last good shape with the remembered total, so the midnight to 08:00 period still has one.
- Handle the two daylight-saving days (46 and 50 real slots) by mapping on local clock time.
- Add a short clause to the decision reason only when a shape was used: "Solar follows your forecast's shape." Reasons are output, so goldens move only for those cases.
**Tests:**
- With `solar_shape=None`, `tests/core/golden_rules_grid.json` and `golden_charge_targets.json` are **unchanged**. This proves the refactor.
- Synthetic shapes: south (bell), east (peak near 10:00), west (peak near 16:00), flat. Assert the direction of the effect, not exact numbers.
- Invalid shapes (wrong length, negative, NaN, all zero) fall back and do not raise.
- Use frozen 2031 dates, including the two clock-change days.
**Done when:** the engine golden snapshots are unchanged for every existing case.

#### FS3. Say which shape was used. Size S

**Work:** an attribute `solar_profile_source` (`forecast` or `standard curve`) on the sensor behind the Plan forecast tile described in `docs/dashboard.md`. Find it in `sensor_descriptions/forecast.py` and say which one you chose. Add it to the unrecorded attributes list if it changes often (`tests/test_unrecorded_attributes.py`). Update `docs/concepts.md` ("Simulation") and `docs/dashboard.md`.

---

#### SR1. Seasonal rules as configuration. Size L

**Goal:** the winter and shoulder months, and the winter behaviour, are settings with sensible defaults.
**New settings (search `const.py` first. Reuse names where they exist):**
- `charge_winter_months`: a list of months 1 to 12.
- `charge_shoulder_months`: a list of months 1 to 12.
- `charge_winter_uses_forecast`: a boolean, default off, which keeps today's behaviour.
**Defaults, computed at read time and not stored until the user edits them:**
- Home Assistant latitude zero or north: winter `(12, 1, 2)`, shoulder `(3, 4, 10, 11)`. These are today's constants.
- Latitude south: the same months shifted by six: winter `(6, 7, 8)`, shoulder `(9, 10, 4, 5)`.
- Tropical latitudes are not designed for here. Allow empty lists, which disable the rule.
**Where:** the Configure "Battery and charging" page, as a set-once field (`.claude/rules/home-assistant.md`: a tuned setting is a control, a set-once setting is a field). Two multi-select month fields and one boolean. Validation: a month may not be in both lists.
**Reload policy:** the keys are in `LIVE_KEYS`, with their row in `tests/core/test_reload_policy.py`.
**Tests:** a schema test (`tests/test_config_flow_schemas.py` uses the real selectors), the options form golden (`tests/ha_e2e/golden/config_flow_forms.json`, regenerate with an explanation), and a save test that proves no reload.

#### SR2. Use the settings in the engine. Size M

**Work:** thread the three values through `ChargeInputs`. `calculate_overnight_charge_target` replaces its direct use of `CHARGE_WINTER_MONTHS` and `CHARGE_SHOULDER_MONTHS` with them.
**Proposed behaviour for `charge_winter_uses_forecast = true` (confirm with the maintainer before you build it):** a winter month runs the normal plan with the shoulder floor (`CHARGE_SHOULDER_MIN_SOC`) in place of the fixed 100% target.
**Tests:**
- With the northern defaults, `golden_rules_grid.json` and `golden_charge_targets.json` are unchanged.
- Southern defaults, custom lists, empty lists, and the new behaviour each get their own cases.
- Use frozen 2031 dates.

#### SR3. Docs. Size S

**Work:** rewrite the sentence in `docs/concepts.md` that says the month lists are fixed and follow northern hemisphere seasons. Update `docs/configuration.md` and `CHANGELOG.md`.

---

### 9. Cards: system types (SY) and the GivEnergy EV charger (GE)

**Both groups are blocked until the maintainer supplies real entity lists (U4, U5).** Do not write discovery code from memory or from another project's documentation. If the fixtures are missing, raise it in your first reply and move on to the other cards.

#### SY0. Fixtures. Owner: maintainer. Then you tidy them

Anonymised entity lists (state, attributes, device name, unit) from GivTCP, one per configuration in **Appendix D** that is marked "fixture needed". Appendix D is the test matrix: it says how each configuration presents itself and what each one must prove. Replace serials with placeholders that keep the **pattern** (length, letters, digits). Remove IP addresses and names. Put them in `tests/fixtures/givtcp_systems/`. Add the GivTCP version for each.

#### SY1. Discovery that does not assume one inverter or one prefix. Size L

**Facts (from GivTCP's published settings):**
- GivTCP supports up to three inverters. The Home Assistant entity prefix is configurable per inverter (`HADEVICEPREFIX`, `HADEVICEPREFIX_2`, `HADEVICEPREFIX_3`), and the default is `GivTCP`. **Today's discovery looks for `givtcp` and its serial.** A user who changed the prefix may not be found.
- GivTCP's guidance for parallel All-In-One systems: control **only the gateway**. The individual units are information only.
- Predbat's documentation says its serial pattern fails on All-In-One and three-phase systems and that you set the serial by hand. Use that as a warning that the same failure is likely here. **Do not copy its pattern.**
**Work (`inverter/givtcp/discovery.py`):**
1. Find every inverter-like device, not only the first. Identify it by the **suffixes** of entities that GivTCP creates (use the suffix lists already in the code), not by a fixed `givtcp` prefix. Prove each suffix against a fixture.
2. Return one `InverterIdentity` per device: serial, prefix, `kind` (hybrid, AC-coupled, All-In-One, gateway, three-phase, EMS, unknown), the GivTCP version (`GivTCP_Version`, where it is readable) and the entities found.
3. **Classify by what GivTCP says, in this order:** (a) `Invertor_Type` if it is readable as an entity state (U10); (b) otherwise the **fingerprints** in Appendix D.2: datapoints that exist only on one kind, such as `Grid_PhaseN_Voltage` (three-phase), `Parallel_Total_AIO_Number` (gateway) or `Plant_Status` (EMS). Treat serial prefixes only as **hints**. Never branch on them alone.
**Tests:** one test per fixture. A prefix-changed fixture is mandatory.

#### SY2. Selection rules and the wizard. Size L

**Rules:**
- One inverter: use it.
- A gateway is present: control the gateway. The units are read-only information.
- One All-In-One and no gateway: control it.
- Several other inverters: **ask**. Do not pick for the user and do not add them together.
**Work:** the setup System page and Reconfigure show what was found, in plain words, and offer a select only when the choice is ambiguous. Reconfigure's manual choice stays. Keep the twelve wiring keys and the stored shape. Do not migrate.
**Tests:** the setup and reconfigure end-to-end tests per fixture. `tests/ha_e2e/golden/config_flow_forms.json` changes. Regenerate it on purpose and explain it.

**Beyond SY1 and SY2, the full detection and management design is in Part B (the design pack) section 1.5:** the role resolver and aggregation rules, the pre-flight "can it charge" check, the effect check after a write, the version-correction table, re-detection, and the clock-drift spike. Build SY1 and SY2 against it, and raise anything that disagrees with the code before starting.

#### SY3. Docs and honesty. Size S

**Work:** a "Which serial do I use?" section in `docs/quick-start.md`. The README and changelog list which system types were tested against **real hardware** and which only against fixtures. Until someone confirms a type on real hardware, say "not tested on real hardware".

#### SY4. Survive a GivTCP upgrade. Size M. Part can start after IB5

**Goal:** upgrading GivTCP from 3.5 to 3.6 must not break the integration or book false energy. Users will upgrade over the coming weeks, and the upgrade changes entity sets and, on a Gateway, the units of the energy totals (Appendix D.7).
**Work:**
1. **Counter guard** in `accumulation.py` (can start now). A cumulative counter whose increase between two readings exceeds what the system could deliver in the elapsed time (the inverter's maximum power times the time, with a margin) is a **baseline reset**, not energy. A step of about 1000 times is logged as a probable unit change. Nothing is booked, one line is logged, and the next reading continues from the new baseline.
2. **Re-detect on change.** When `GivTCP_Version` or the set of role entities differs from the stored identity hash (Part B 1.5.7), re-classify. If the kind, controller or module count differs, raise the repair "The system looks different" naming what changed. Never switch controller silently.
3. **Vanished or renamed entities.** Store each GivTCP entity reference as the registry **unique id** as well as the entity id, and resolve the current entity id from the registry each cycle. GivTCP 3.6 and 3.6.1 reset renamed entity ids to their defaults, so a stored id can stop matching while the unique id still does. **Check how the integration stores these references today** and keep the old id as the fallback. When neither resolves (an HV Gen 3 hybrid moving to the single-phase set), offer a re-map in Reconfigure, matched by suffix, with the old and new ids shown.
4. **Docs.** A short "Upgrading GivTCP" section: what to expect, and that Home Assistant will show one large energy spike for Gateway totals used in the Energy dashboard, which is corrected in Developer Tools, Statistics.
**Tests:** a counter that steps 1000 times (nothing booked, baseline reset); an entity id reset to the default while its unique id is unchanged (resolved, no repair); a missing configured entity (repair, no crash); an unchanged system (no repair); fixtures before and after for an HV Gen 3 hybrid.
**Done when:** a simulated 3.5 to 3.6 upgrade leaves the plan, the cost counters and the dashboard intact, or raises one clear repair.

---

#### GE0. Fixtures for the GivEnergy EV charger. Owner: maintainer

**Status:** GivTCP 3.6 documents the charger's entities, listed below, so GE1 to GE3 can start against the documented names with fake entities clearly labelled as such. A real fixture is still needed for the exact state strings and entity ids.

An anonymised GivTCP entity list from a system with a GivEnergy EV charger: names, states, attributes, units, and the GivTCP version.
GivTCP's datapoint reference (`docs/DATAPOINTS.md`) names the charger's datapoints, which the fixture must match: reads `Charging_State`, `Connection_Status`, `Error_Code`, `Active_Power`, `Charge_Session_Energy`, `Charge_Session_Duration`; controls `Plug_and_Go` (switch), `Charge_Control` (select, `Start` or `Stop`), `Charging_Mode` (select, `Grid`, `Solar` or `Hybrid`), `Charge_Limit` (number, 6 to 32 A), `Import_Cap` and `Max_Session_Energy`. It appears in Home Assistant as a device named "GivEVC". **The datapoint names are not entity ids.** Take the entity ids, the prefix and the state strings from the fixture.

#### GE1. Discover and read the charger. Size M

**Work:** add `EVChargerBrand.GIVENERGY` and `_discover_givenergy_evc(all_states)` in `discovery/ev_charger.py`, mapped to the same normalised interface as the other brands (`EVCharger`, `EVChargerState`). Add it to `discover_ev_chargers`. Normalise its states to disconnected, connected, charging, paused, completed and unknown.
**Rule:** `.claude/rules/safety.md` applies. The charger may be absent or added later. Both paths are tested.
**Note:** GivTCP's README records a firmware bug (version 1.12 and below) where the charger's local Modbus port works on WiFi only. Put that in `docs/troubleshooting.md`.
**Tests:** a fixture-driven discovery test with the charger present, absent and added after setup.

#### GE2. Set the charger's mode. Size M

**Goal:** the integration sets the GivEnergy charger the way it sets a Zappi.
**Mapping (confirm with the maintainer before you build it):** the logical mode "use surplus only" (Eco+ for a Zappi) maps to the GivEnergy **Solar** mode. Never choose **Grid**. Never use Charge Control to stop a session. Never turn Plug and Go off. Do not choose **Hybrid** automatically: it takes a constant 6 A from the grid.
**Work:** one function maps a brand-neutral logical mode to the brand's option. `_apply_ev_action` and `_send_ev_mode` use it. Dry run records `Would set ...` and sends nothing. The cooldown applies.
**Tests:** for each brand with a mode select, the mapping table. Dry run. Never-stop and never-grid tests that **fail** if a forbidden option is ever selected.

#### GE3. Docs and messages. Size S

**Work:** `README.md`, `docs/configuration.md` (the EV charger list), `docs/entities.md`, the changelog. Remove the statement that the GivEnergy charger is not supported. `tools/mock_givtcp.py` gains the charger entities from the fixture.

---

### 10. Cards: housekeeping (HK) and release (RN)

#### HK1. README accuracy. Size S

**Work:** replace "Works with any supplier and any tariff" with what is true: flat, day and night, or up to five timed rates; no dynamic tariffs; the bill estimate assumes monthly bill periods, one supplier discount, one VAT rate and one flat levy per period. **Keep the wording generic.** No maintainer, no household.

#### HK2. Progress notes. Size S

**Work:** `docs/design/PROGRESS.md` still says "Merged cards: none yet" after 0.18.0 shipped. Correct it. Start a section for this release. `ROADMAP.md`: tick what is done, and add the "Won't have" reasons for export and dynamic tariffs if missing.

#### HK3. Outstanding browser checks. Owner: maintainer (U7)

Run the manual checks in `docs/design/spikes/SP2.md` on a real instance: the Community dashboards entry, `getCreateSuggestions`, Take control, the distribution card. Record the result in that file. If Take control freezes the Settings view into a dashboard everyone can open, open an issue.

#### HK4. Requirements and quality scale. Size S

**Work:** `REQUIREMENTS.md` (the write behaviour changes). `quality_scale.yaml` and the claim in `CLAUDE.md` stay accurate. Check that hassfest passes in CI (it could not run locally for 0.18).

#### SP0. The specification method. Size S. Ships first
**Goal:** the method for learning from other projects is written down where the agent and the maintainer both read it.
**Work:** add `docs/design/specs/README.md` from Part C (specifications) section 1 (roles, the specification template, what a specification may and may not contain, provenance). Add `SPEC-001` as `docs/design/SPEC-001 in Part C from section 2. Add the rule to `CLAUDE.md` (card RU1) as one sentence pointing at the folder. **Do not add the other project's code to the repository, even as a test fixture.**
**Done when:** the folder exists, the README is under two screens, and a reviewer can tell from it what a builder may read.

#### SP1. Check the charge simulation against SPEC-001. Size M. After IB1 to IB5
**Goal:** know where our overnight target differs from a published method, with numbers. **No behaviour change.**
**Work:** write `tests/core/test_charge_spec_vectors.py` with the four scenarios in SPEC-001 section 2.9 as inputs to `calculate_overnight_charge_target`, using the same capacity, reserve, window, load, forecast scales and weights (map the weight to our conservatism: weight 35 is 37.5 percent toward the low estimate, so our fraction would be 0.375 to compare like with like). **Do not assert PALM's numbers.** Record our numbers beside them in `docs/design/SPEC-001 in Part C, answer the seven questions in section 2.10, and mark each difference as: same idea, deliberate difference, or question for the maintainer.
**Stop and ask** if a difference changes the target by more than ten percentage points on any scenario. That is a decision for the maintainer, and it would move golden files.
**Done when:** the comparison file exists and the maintainer has read it. The tests pin our current behaviour and pass.

#### SP2. Write and review the specifications. Size L, a series. Not blocking
**Status:** the reader step is done for these, in Part C (specifications) and Part C: SPEC-001 (PALM overnight target), SPEC-003 (load history and away mode), SPEC-004 (diverter in the plan), SPEC-005 (hardware detection and gating), SPEC-006 (cheapest-window selection), SPEC-007 (surplus allocation), SPEC-008 (departure-time plan), SPEC-009 (condition-matched forecast correction), and approach notes on HAEO. Each states what was and was not read.
**Work:** (1) copy them into `docs/design/specs/`; (2) the maintainer reviews each before a builder uses it; (3) write the remaining ones in the backlog, SPEC-002 (forecast interfaces) first because FS1 needs it; (4) each specification that has numbers gets test vectors, from a reference model written from the specification.
**Rules:** no code in a specification. A specification that cannot be written without copying says so and stops. **Specifications are inputs to cards, not cards.** A card that uses one names it, and the PR says which questions in the specification it answered.

#### RM1. Roadmap: the competitor review. Size M. Ships with HK2

**Goal:** the gaps found in other GivEnergy systems are on the roadmap, with context, evidence and links, and the items this release delivers are marked.
**Read first:** Part D (gap analysis) (the analysis), Appendix F of this brief (the exact roadmap text) and Part B (the design pack) (the design for every item: flows, pseudocode, vectors, open questions). Write Part B to `docs/design/FEATURE_DESIGNS.md` so each roadmap row can point at its section.
**Work:**
1. Add the **new items** in Appendix F.1 to `ROADMAP.md`, each in its bucket, in the table format already used (Item, What and why, Evidence, Indicative value per year, Size). New ids are S19, C28 to C34 and N19 to N24. **Ids are stable and never reused.** Do not renumber.
2. **Append** the evidence in Appendix F.2 to the existing rows. Do not duplicate an item that already exists. Where a row says what this release delivers, say "in v0.19" in the What and why column. When the release ships, the changelog records it and the row moves to Shipped, as the roadmap already does for earlier work.
3. Add the rows in F.3 to **Won't have for now**, F.4 to **Known limitations**, and F.5 to **Open questions**.
4. Rewrite **C23** as in F.2. The administration it planned for has happened.
5. Keep the roadmap's rules: UK English, no em dashes, generic text (no maintainer, no one household), short sentences, values "Not applicable" or "Not measured" where nothing was measured. **Do not invent values.**
6. **Check every link** against the source it names. If a link cannot be opened, say so in the PR and keep the text without the link. Do not guess a URL.
**Tests:** none for text. `tests/test_metadata.py` and any test that reads `ROADMAP.md` must still pass. Search for tests that name roadmap ids before you rename or move rows.
**Done when:** a reviewer can follow each new item from the roadmap to the source that motivates it.

#### RN1. Changelog. Size S

Headings **Added**, **Changed**, **Removed**.
- **Removed:** the three Current Rate attributes. Say what they showed and that rates are managed in Configure only.
- **Changed:** the setup tariff page can start from GivTCP's rates; retry and re-plan; seasonal rules are configurable; discovery handles more system types.
- **Added:** the GivEnergy EV charger; the Charge Target Conflict sensor and banner; the forecast shape.
UK English. Name the thing, not a roadmap id.

#### RN2. Release. Size S

Use `/release`. Tag pre-releases first (`v0.19.0b1`, then `v0.19.0rc1`), as the pre-release workflow expects. The maintainer rehearses on the test instance, then runs one night in dry run before turning it off.

---

### 11. Order of work and the PR stack

| Step | Cards | Why this order | Blocked by |
|---|---|---|---|
| 1 | IB1 → IB2 → IB3 → IB4 → IB5 | The mechanical move. Nothing changes for the user. Golden files must not move. | none |
| 1a | SP0, then SP1 | The method comes first. SP1 waits for the simulation to be in its final place. SP2 runs alongside and is not blocking, except that FS1 uses SPEC-002. | step 1 |
| 2 | IB6, RA1 | Removing the comparison before the rename means there is nothing to rename. | step 1 |
| 3 | IB7 | The contract tests need the finished interface. | step 1 |
| 4 | RA2 → RA3 | Rate defaults need the adapter method. | step 2, U6 |
| 5 | CC1 → CC2 → CC3 | Independent of the writes. Starts as soon as CC1 has its entity list. | U1 |
| 6 | WS1 → WS3 | Retry first. Re-plan needs it. | step 1 |
| 7 | WS2 | The riskiest card. Its own PR. | WS1, U2 |
| 8 | SR1 → SR2 → SR3 | Behaviour change with golden changes. | step 1 |
| 9 | FS1 → FS2 → FS3 | Needs real provider data. | U3 |
| 10 | SY0 → SY1 → SY2 → SY3. **SY4 can start after IB5** | SY0 to SY3 need fixtures. SY4's counter guard does not. | U5 |
| 11 | GE0 → GE1 → GE2 → GE3 | Needs fixtures. | U4 |
| 12 | RU4, HK1 to HK4, RM1, RN1, RN2 | Last. RU1 to RU3 are not here: they ship inside the cards above. RM1 ships with HK2. | all |

Cards in steps 5 to 9 are independent of each other. Start whichever has its evidence.

**Rules for the stack:** branches are `r019/<topic>`. Conventional Commits. Each PR states what it checked and what it could not (`Testing` in the PR template). Behaviour cards state which golden files moved and why. Refactor cards state that none did.

---

### 12. What the maintainer has to do

| # | Task | Needed for |
|---|---|---|
| M1 | **Answered by the 3.6 documentation (no entity). Optional.** In Developer Tools, States, search "smart" and "palm" on your GivTCP. | CC1 (U1) |
| M2 | Confirm whether a changed charge target during an open window is applied (a real test on the test instance, or GivTCP's source). | WS2 (U2) |
| M3 | Supply Solcast and Forecast.Solar entity states and attributes for tomorrow, from real instances. | FS1 (U3) |
| M4 | Supply anonymised entity lists for the configurations in Appendix D marked "fixture needed", highest priority first. | SY0 (U5) |
| M5 | Supply an anonymised entity list from a GivEnergy EV charger system. | GE0 (U4) |
| M6 | **Answered from the 3.6 source (defaults 0.395, 0.155, 0.04). Nothing to do.** | RA2 (U6) |
| M7 | Run the SP2 browser checks. | HK3 (U7) |
| M8 | Decide: the GivEnergy charger mode mapping (GE2); the winter-with-forecast behaviour (SR2); whether re-planning needs a control (WS2). | those cards |
| M9 | Rehearse on the test instance and run one dry-run night. | RN2 |
| M10 | **Mostly answered by the 3.6 datapoints list.** On your own GivTCP, confirm these entities exist and note the exact strings: `Charge_Target_SOC_1`, `Invertor_Type`, `Data_Age`, `GivTCP_Version`, `Battery_Capacity_kWh` and `Battery_Capacity_kWh_calc`. Note the GivTCP version. | U8, U10, SY1 |
| M11 | Decide the minimum GivTCP version to support (Appendix D.3). | U11 |

---

### 13. Definition of done (the release)

- [ ] Every card merged, or explicitly dropped with a reason in `PROGRESS.md`.
- [ ] `ruff check`, the unit suite and the end-to-end suite are green, and the floor job (2026.5.0) is green.
- [ ] No GivTCP entity-name string remains in `coordinator.py` or `core/`.
- [ ] Every golden file change is listed in a PR with the reason. Refactor PRs list none.
- [ ] Every new write path has a dry-run test that asserts nothing was sent.
- [ ] The three Current Rate attributes are gone and the changelog says so.
- [ ] `docs/sensors.md` is regenerated and `tests/test_docs_sensor_table.py` passes.
- [ ] Docs and strings are generic and in UK English.
- [ ] The README says which system types were tested on real hardware.
- [ ] The maintainer has rehearsed on the test instance and run one night in dry run.
- [ ] Every rule and skill statement that this release made untrue has been fixed, and the audit in card RU4 found nothing left.
- [ ] The specification method is in `docs/design/specs/` with SPEC-001 and its comparison (cards SP0 and SP1), and no code from another project is in the repository.
- [ ] `ROADMAP.md` has the competitor-review items, evidence and links (card RM1), and every link was checked.

---

### 14. Risks

| Risk | Effect | What to do |
|---|---|---|
| WS2 writes a target that GivTCP ignores mid-window (U2) | The plan and the inverter disagree | Verify first. Ship it off by default if unverified. |
| Retry and re-plan increase register writes | Inverter register wear (a lifetime budget) | Hard caps, the existing cooldown, and the write count shown in the log. |
| GivTCP's prefix is configurable (SY1) | Users who changed it are not found today | Suffix-based discovery, plus Reconfigure's manual choice. |
| RA2 pre-fills a GivTCP default that looks real (U6) | A wrong rate gets confirmed unread | Skip known defaults. Label the field. |
| The competing-controller check has false positives (CC2) | A warning after an app change | The wording says "something else". It clears by itself. |
| The forecast shape is misread (time zone, units) (FS2) | A worse target than the bell curve | Validate hard. Fall back silently. Prove with fixtures from real instances. |
| Untested system types (SY) | Wrong inverter controlled | Never auto-pick between several inverters. State "not tested on real hardware". |
| The refactor changes behaviour by accident (IB) | Silent regressions | Golden files and the end-to-end write test are the check. |
| The write sequence does not stop a charge at the target on per-slot-target inverters (U8) | The battery charges to 100% at the cheap rate | A real-charge test on such an inverter before the release. Fix the sequence in its own card. |
| GivTCP signs and entities differ by version (Appendix D.3) | Wrong planning on the Gateway or a renamed entity set after an upgrade | Fixtures from two versions, the entities-missing repair, a minimum supported version. |
| One person reviews all of it | Review fatigue | Small PRs, the order above, and the evidence in each PR. |

---

---

### 15. Rules and skills that change with this release

The rule files are the contract between the maintainer and the agent. This release changes how the code is organised and what it may write. Several sentences in `CLAUDE.md` and `.claude/rules/` therefore become false or incomplete. **A rule that no longer matches the code does more harm than no rule**, because the next change will follow it.

**How:** each rule change ships in the **same PR** as the code that makes it true. The PR body has a "Rules changed" line. Reviewers read the rule diff first.

#### 15.1 What changes, by file

| File | Statement today (found at v0.18.0) | Why it changes | New content | Ships with |
|---|---|---|---|---|
| `CLAUDE.md`, "What this is" | "It reads GivTCP entities for a GivEnergy inverter, plans the overnight charge..." | The integration talks to the inverter through a backend. GivTCP is the only one. | Say so in one sentence. | IB4 |
| `CLAUDE.md`, Layout table | `coordinator.py`: "Thin Home Assistant bridge: reads states, calls `core/`, applies writes, runs timers" | It reads through the backend, decides what to write, and also runs retries and re-plans. | Reword the row. Add rows for `inverter/` (the backend interface), `inverter/givtcp/` (the only code that knows GivTCP entity names, the write sequence and the writer) and `core/inverter_values.py`. | IB1 to IB4 |
| `CLAUDE.md`, "GivTCP sign conventions" | "The coordinator negates both on read (`_collect_raw` in `coordinator.py`)" | The adapter negates. `_collect_raw` only merges. | Name the adapter. Retitle the section "Inverter sign conventions". Keep the two named tests. | IB5 |
| `CLAUDE.md`, "Architecture rules" | (no rule about where GivTCP names live, who owns the rates, or who writes the target) | New constraints. | Three bullets: only `inverter/givtcp/` builds GivTCP entity names or calls GivTCP services; this integration owns the rates and GivTCP's only pre-fill the setup tariff page; this integration alone writes the charge target and a second controller shows as the Charge Target Conflict sensor, never as a repair. | IB4, RA2, CC3 |
| `.claude/rules/safety.md`, "Dry run" | "Writes to GivTCP go through `givtcp_writer.py`... Do not call a GivTCP service from anywhere else." | The writer moves. The coordinator no longer writes. | New path `inverter/givtcp/writer.py`. "Only the adapter writes to the inverter. The coordinator calls the backend." | IB3, IB4 |
| `safety.md`, dry-run list | Lists the charge target and window, the skip-charge minimum, the cheap rate floor top-up, the EV mode change, the charge slot clear and the immersion actuator. | New write paths. | Add the retry, the re-plan and the GivEnergy charger mode. Each needs a dry-run test. | WS1, WS2, GE2 |
| `safety.md`, "What the integration never does" | "It never stops or pauses an EV charger. For a Zappi... Eco+ and never Stopped or Fast." | A second charger type. New write limits. | GivEnergy charger: Solar, never Grid, never Charge Control stop, never Plug and Go off. Re-plan: at most 3 extra target writes a night, never outside the window, never opens a window. Rates are never written back to GivTCP. | GE2, WS2, RA2 |
| `safety.md`, write audit | "The write audit only records. It never reverts a change and never raises a repair." | A new feature reads the audit log. | Keep the sentence. Add that the Charge Target Conflict sensor and banner read the log and nothing else. | CC3 |
| `.claude/rules/core-purity.md`, "What core/ is" | "Anything Home Assistant specific goes in `coordinator.py` or a platform file." And the import list: stdlib, `const`, `discovery`, `logging`. | A new package `inverter/` exists, and `discovery/` loses its GivTCP part. | HA-specific code lives in `coordinator.py`, a platform file or `inverter/`. `core/` never imports `inverter/`. Seasonal months, the forecast shape and the re-plan inputs are **passed in** (`ChargeInputs`, `ReplanInputs`), never module constants read inside a function. | IB1, SR2, FS2, WS2 |
| `.claude/rules/tests.md` | Nothing about fakes, contract tests or fixtures. | New test kinds. | `tests/fakes/fake_inverter.py` and `tests/backend_contract.py`: any backend must pass the contract. **No discovery or mapping code without an anonymised fixture from the real system. Never guess entity names from memory or from another project's docs.** Retry and re-plan tests use a controlled clock. | IB7, SY1, GE1 |
| `.claude/rules/home-assistant.md` | Entity rules, flows, reloads. Nothing on where inverter entity names are built. | Same constraint as in `CLAUDE.md`, in detail. | Inverter entity names are built only in `inverter/givtcp/`. Retry and re-plan timers are `@callback` functions and are cancelled on unload. The platforms are `sensor`, `number` and `switch`: a new platform needs a reason in the PR. | IB4, WS1, CC3 |
| `.claude/rules/dashboard.md` | The golden file, who sees Settings, HACS cards. | A new banner, and the 2026.5 floor. | Banners (dry run, test instance, charge target conflict) share one place and order. At the 2026.5 floor use only `state` and `numeric_state` conditions, because the wider set needs 2026.10. | CC3 |
| `.claude/rules/docs-and-style.md` | Generic docs, commits, changelog. | An attribute removal and a rule-change habit. | A removed or renamed attribute goes under "Removed" in the changelog with what it showed. A change that makes a rule untrue changes the rule in the same PR. | RA3, RN1 |
| `.claude/skills/regenerate-goldens/SKILL.md` | A table of goldens and the command for each. | This release moves `config_flow_forms.json`, `golden_dashboard_matrix.json` and one field in `golden_engine_snapshots.json`. | Check that every golden this release touches is in the table with its command. Add a line: a refactor card must move none. | RA1, CC3 |
| `.claude/skills/add-sensor/SKILL.md` | The steps for a new sensor. | CC3 adds a diagnostic enum sensor. | Check the skill covers a diagnostic sensor with an enum state and an `entity_category`. Add the case if it does not. | CC3 |
| `docs/testing.md`, `docs/design/mock_givtcp.md`, `docs/architecture.mermaid`, `REQUIREMENTS.md`, `ROADMAP.md` | Describe the old layout and the once-a-day write. | The code moves and the write changes. | Update each in the PR that changes the thing it describes. | IB7, WS1, HK2, HK4 |

I have not read every line of every rule file or skill. The table lists what a search found. RU4 closes the gap.

#### RU1. `CLAUDE.md`. Size S. Ships with IB1 to IB5

Make the edits in the first four rows of 15.1, and add one sentence pointing at `docs/design/specs/` and saying that other projects are studied by specification and never copied. Check the file is still under 150 lines (it is 111 now). If it would not be, move detail into a rule file.

#### RU2. `safety.md`. Size S. Ships with IB3, IB4, WS1, WS2, CC3, GE2, RA2

Make the edits in the four `safety.md` rows. Each new write path gets its dry-run test in the same PR. A reviewer can then check each new sentence against a test.

#### RU3. The other rule files and the skills. Size M. Ships with the matching cards

Make the edits in the remaining rows. Do not batch them at the end: a stale rule in the middle of the stack misleads the next card.

#### RU4. Audit. Size S. The last card before the release

Read every file in `.claude/rules/`, `.claude/skills/` and `CLAUDE.md` against the finished code. List every sentence that is no longer true, every path that no longer exists, and every rule that a new feature breaks. Fix them. Put the list in the PR. Do not skim: open each named file, function and test and check it exists.

### Appendix A. Identifiers to move, rename or remove

Found by text search at v0.18.0. Search again. The counts will have changed.

| Identifier | Action |
|---|---|
| `discover_givtcp_inverters`, `GivTCPInverter`, `get_suggested_entities`, `discover_battery_cycle_entities`, `inverter_temperature_entity_ids`, `ActiveChargeSlot`, `describe_charge_slots`, `find_other_active_charge_slots`, `GIVTCP_PREFIX` | Move to `inverter/givtcp/discovery.py` (IB2) |
| `GivTCPWriter`, `VerifiedWrite` | Move to `inverter/givtcp/writer.py` (IB3) |
| `log_givtcp_write` (in `logging.py`) | Stays in `logging.py`. `tests/golden_logging.json` pins the log wording, so do not change any message text |
| `GIVTCP_MIN_WRITE_INTERVAL_S`, `GIVTCP_MAX_WRITE_RETRIES`, `GIVTCP_WRITE_RETRY_SLEEP_S`, `GIVTCP_WRITE_LIFETIME_WARN`, `GIVTCP_MIN_CHARGE_TARGET_PCT`, `GIVTCP_MAX_CHARGE_TARGET_PCT` | Move to `inverter/givtcp/constants.py` (IB3) |
| `_givtcp_set_switch`, `_givtcp_set_select`, `_givtcp_set_number` | Move into the adapter (IB4) |
| `_write_overnight_target`, `_write_minimum_target`, `_async_apply_charge_target`, `_write_charge_window`, `_write_floor_target`, `_clear_charge_slot`, `_other_charge_slots`, `_check_other_charge_slots` | Move the sending into the adapter. The coordinator keeps the decision (IB4) |
| `_collect_raw`, `_read_power_inputs`, `_read_daily_counters`, `_read_charge_rate_w`, `_read_tracked` | The inverter part moves into `backend.read` (IB5) |
| `_require_givtcp_publishing`, `_note_givtcp_publishing`, `_note_givtcp_silent`, `_givtcp_was_unavailable` | Behind `is_publishing()` (IB5) |
| `ISSUE_GIVTCP_ENTITIES_MISSING`, `async_create_givtcp_missing_issue`, `async_delete_givtcp_missing_issue` | **Keep the issue id and the text.** Internal calls may change. |
| `GivTCPRates`, `RateMismatch`, `givtcp_rate_mismatches`, `_read_givtcp_rates`, `_compare_givtcp_rates`, `givtcp_rate_entity_ids`, `GIVTCP_RATE_SUFFIXES`, `GIVTCP_RATE_TOLERANCE_PCT`, `core/tariff_check.py` | **Remove** (RA1). RA2 replaces the reading with `read_rate_defaults()` |
| Attributes `givtcp_rate_differences`, `givtcp_rates_differ`, `givtcp_rate_attributes` | **Remove** (RA1) |
| `CHARGE_WINTER_MONTHS`, `CHARGE_SHOULDER_MONTHS` | Stay as the defaults. Used through `ChargeInputs` (SR2) |
| `_make_solar_slot_weights`, `_SOLAR_SLOT_WEIGHTS` | Stay as the fallback shape (FS2) |

### Appendix B. Tests and golden files expected to change

| File | Changes in | Reason |
|---|---|---|
| `tests/core/golden_engine_snapshots.json` | RA1 | The removed field only |
| `tests/ha_e2e/golden/config_flow_forms.json` | RA2, SR1, SY2 | New or changed form fields |
| `tests/golden_dashboard_matrix.json` | CC3 | The new banner |
| `tests/ha_e2e/test_entity_snapshot.py` | CC3 | The new sensor, on purpose |
| `tests/core/golden_rules_grid.json`, `golden_charge_targets.json` | **none, by design** | If one moves in FS2 or SR2 with default inputs, the refactor is wrong. Stop. |
| `tests/test_docs_sensor_table.py` | CC3 | Regenerate `docs/sensors.md` |
| `tests/core/test_reload_policy.py` | SR1 | Rows for the new keys |
| `tests/golden_accumulation.json` | none | WS1 adds no stored field |

### Appendix C. Questions to put to the maintainer in your first reply

1. Do you agree with the package layout in section 5.2, or do you want the adapter elsewhere?
2. Where should the dry-run check live: in the coordinator before the call, or passed into the adapter as a port, as `immersion_actuator.py` does?
3. Is re-planning enabled by default (after U2), or off behind a control?
4. For `charge_winter_uses_forecast`, is the proposed behaviour (the normal plan with the shoulder floor) what you want?
5. For the GivEnergy charger, is "Solar" the right match for Eco+, and should "Hybrid" ever be chosen automatically?
6. What should happen when GivTCP holds a default rate such as 0.155 (U6)?
7. Is there anything in the rule files you want changed beyond section 15?

### Appendix D. Inverter configuration test matrix (GivTCP first)

**Purpose:** the list of ways a GivEnergy system presents itself **through GivTCP**, and what each one must prove in this integration. GivTCP is the only communication layer, so what it publishes is what we get. This is the checklist for cards SY0 to SY3 and the contract tests in IB7.

#### D.0 Sources, and what "verified" means

- **Primary: GivTCP's own documents,** read at version 3.6.0-beta1 (released 1 October 2026): `docs/DATAPOINTS.md` (every value GivTCP publishes, by device), `SETTINGS-GUIDE.md` (the controls), and the release notes. Claude Code reads them again at the version in each fixture. Do not work from this summary.
- **Secondary:** Predbat's published documentation (how users wire it), the `givenergy-modbus` supported-hardware table, GivEnergy's manuals. Used for ideas and cross-checks only.
- **What none of them give is the Home Assistant entity id** for each datapoint. They give datapoint names and one example (`sensor.givtcp_<serial>_soc`). Entity ids, prefixes and state strings come from fixtures.
- **3.6.0-beta1 is a beta.** Many of its changes (D.3) mean older GivTCP behaved differently. Every fixture records `GivTCP_Version`.

#### D.1 What GivTCP publishes for every system

From the datapoint reference:

- **Signs.** `Grid_Power`: positive is export, negative is import. `Battery_Power`: positive is discharging, negative is charging. `Invertor_Power`: positive is output, negative is AC charging the battery. (Matches what `CLAUDE.md` says the coordinator negates today.)
- **Health values** for all devices: `status` (online while GivTCP is reading), `Time_Since_Last_Update`, `Data_Age` (seconds, `-1` if nothing yet, large when values are being held from the last good read), `Write_Count`, `GivTCP_Version`.
- **Numbered families** are written once with `N`: `Charge_Target_SOC_N` means slots 1 to 10. "How many slots appear depends on what the inverter supports."
- **Inverter details** (attributes of the inverter device in Home Assistant, so possibly not entity states, see U10): `Invertor_Type` ("Hybrid, AC, AIO, three-phase, EMS, Gateway, ..."), `Invertor_Max_Inv_Rate`, `Invertor_Max_Bat_Rate`, `Battery_Capacity_kWh`, and `Battery_Capacity_kWh_calc` ("calculated by GivTCP from the battery modules").
- **The controls this integration uses:** `Enable_Charge_Schedule`, `Charge_start_time_slot_N` and `Charge_end_time_slot_N` (selects, and from Home Assistant 2026.5 also `time` entities that stay in sync), `Target_SOC` ("SOC to stop charging at during a charge slot"), `Enable_Charge_Target` ("stop charging at `Target_SOC`, otherwise charge to 100%"), `Charge_Target_SOC_N` ("target SOC for charge slot N, on inverters with per-slot targets"), `Battery_Charge_Rate` (watts).
- **Rates:** `Day_Rate`, `Night_Rate`, `Export_Rate`, `Current_Rate_Type`, with cost and battery value values, from the Day and Night tariff on GivTCP's config page. Money is in pounds.
- **Batteries:** each battery module is **its own device** (`Battery_Details/Battery_Stack_N/<battery serial>`), with per-module state of charge and capacity **in amp-hours**. High-voltage stacks (three-phase and All-In-One) also have stack-level values (`Stack_SOC_kWh`, `Stack_SOH`, and so on).
- **A GivEnergy EV charger** is a separate device, "GivEVC".
- **External meters** (EM115, EM418) are separate `Meter_Details` entries.

#### D.2 How GivTCP tells the configurations apart (fingerprints)

`Invertor_Type` is a sensor in GivTCP 3.6 (U10). Use these fingerprints as a cross-check and when its value is not recognised. Prove each against a fixture before you rely on it.

| Kind | Datapoints that identify it, from the reference |
|---|---|
| Hybrid, AC-coupled, All-In-One | The `Power/Power` group: `PV_Power`, `Grid_Power`, `Load_Power`, `Battery_Power`, `SOC`, `SOC_kWh`. The `Flows` group (single-phase). PV string voltage and current are **not published on AC-coupled and All-In-One** inverters. |
| Three-phase | The `Power/Power` values plus `Grid_PhaseN_Voltage`, `Load_PhaseN_Power`, `Export_PhaseN_Power`, `Meter_Import_Power`, `Meter_Export_Power`. Extra controls `Force_Charge_Enable`, `Force_Discharge_Enable`, `Force_AC_Charge_Enable`. |
| Gateway | `Gateway_State`, `Gateway_Mode`, `Parallel_Total_AIO_Number`, `Parallel_Total_AIO_Online_Number`, `Liberty_Power`, `Grid_Relay_Voltage`, and per-unit entries `Inverters/AIO_N/...` (N = 1 to 3) with `SOC`, `Invertor_Power`, AC charge and discharge energy. |
| EMS | `Plant_Status`, `Inverter_Count`, `Meter_Count`, plant-level `Calculated_Load_Power`, `Measured_Load_Power`, `Other_Battery_Power`, per-inverter `Inverters/<serial>/SOC` and `Power`, controls `Plant_Control` and `EMS_Charge_Target_SOC_N` (1 to 3). |
| Per-slot charge targets | `Charge_Target_SOC_N` present. GivTCP's release notes name newer Gen 3, Gen 4, All-In-One, HV Gen 3 and three-phase. |
| High-voltage battery stack | `Stack_*` values under `Battery_Stack_N`. Three-phase and All-In-One. |

#### D.3 What changed in GivTCP 3.6.0-beta1 (from its release notes). The final 3.6 is in D.7

These are the facts that make **version** part of every test.

1. **Hybrid HV Gen 3 inverters** (single-phase, 8 and 10 kW) are now read as single-phase. Before, they were read with the three-phase layout, "so values such as SOC and PV power could show as 0, and controls wrote to three-phase registers", and they were labelled All-in-One. Their entities change to the single-phase set and the old three-phase ones are removed.
2. **Gateway battery power had the wrong sign**: discharging showed as charging and the reverse. The same applied to the Gateway's inverter and Liberty power, the power flows, the time remaining, and each All-in-One's power shown through the Gateway. Fixed in 3.6.0-beta1.
3. **The Gateway sets charge and discharge rates for the All-in-Ones behind it** through the AC charge and discharge limit. Before, rate controls failed and the current rates were not shown. Gateway controls that errored now work.
4. **When a poll or a register read fails, GivTCP republishes the last good data.** Entities stay available but old. `Data_Age` was added to expose it.
5. **Pause entities:** Battery Pause Mode and its timeslot are added on Gen 1 (firmware 187 or later), Gen 2, Gen 3, HV Gen 3, All-in-One and Gateway. Pause Mode is added on AC-coupled (firmware 200 or later). Leftover pause entities are removed on older Gen 1, three-phase and EMS.
6. **Per-slot charge and discharge targets** are added on 10-slot inverters (newer Gen 3, Gen 4, All-in-One, HV Gen 3) and on three-phase, where slots 3 to 10 are now read. Charge and discharge rates are added on three-phase.
7. **AC and All-in-One:** the PV string voltage and current entities are removed (the registers hold no real string readings).
8. **A control that is not available on a model now says so** ("not available for Ems inverters"). That covers inverter controls and Force Charge and Export on the EMS.
9. **Slot time entities:** on Home Assistant 2026.5 and later each slot has a `time` entity beside the select.
10. **No fixed limit of five inverters.** REST ports for slots 1 to 5 are 6345 to 6349, from slot 6 they start at 6356. (Earlier documents say a maximum of three.)
11. Inverter details are detected once and saved per serial number.

**Policy to decide (M11, U11):** the minimum GivTCP version we support. Below it, the wizard warns. Do not write compatibility code for every older behaviour. Support what the fixtures prove.

#### D.4 The matrix

Priority: **A** means discovery or the reads are likely to break (test first). **B** likely works but is unproven. **C** probably unsupported, so the test proves a clear message and no write.

| ID | Configuration | How GivTCP presents it | What to prove in this integration | Evidence | Priority |
|---|---|---|---|---|---|
| SYS-01 | **Single-phase hybrid, one battery** (Gen 1 or Gen 3 LV, 3.6 or 5.0 kW). The baseline. | `Power/Power` and `Flows` groups. The controls in D.1. | Everything in D.1. Already run on one 5.0 kW system. Keep it as the golden fixture, and record its generation and GivTCP version. | Real system, one | B |
| SYS-02 | **Hybrid with several batteries** | One device per battery module, with state of charge and capacity **in amp-hours**. At inverter level: `SOC`, `Battery_Capacity_kWh` and `Battery_Capacity_kWh_calc`. The GivTCP setting `NUMBATTERIES_N` gives the count. | **Which capacity entity we use**, and what happens when `Battery_Capacity_kWh` and `Battery_Capacity_kWh_calc` differ. Total across modules, not one module. Per-module entities are never mistaken for the inverter's. Test one, two and five packs. | DATAPOINTS | **A** |
| SYS-03 | **Older Gen 1, three-phase, EMS: pause entities** | Before 3.6 the pause entities existed but did not work. From 3.6 they are removed on those models. | The integration never relies on a pause entity. Fixtures from both versions. | Release notes, Predbat docs | B |
| SYS-04 | **Hybrid Gen 2** | Pause Mode and timeslot added in 3.6. The `givenergy-modbus` library marks Gen 2 **untested**: "no Gen 2 unit has ever been observed". | Discovery does not crash and does not control it silently. Either it works against a fixture or it says "not tested". | Library table | B |
| SYS-05 | **Hybrid HV Gen 3** (single-phase 8 and 10 kW, stackable battery) | From 3.6, single-phase, with the single-phase entity set. Before 3.6, read as three-phase or All-in-One: SOC and PV could be 0 and controls wrote to three-phase registers. | A 3.6 fixture reads normally. A pre-3.6 fixture is **recognised as unreliable** (SOC 0 with a battery present) and the integration refuses to plan. **An upgrade of GivTCP removes and renames entities**, so the existing `ISSUE_GIVTCP_ENTITIES_MISSING` repair must fire and Reconfigure must fix it. | Release notes | **A** |
| SYS-06 | **AC-coupled** | `Power/Power` group without PV string voltage and current. The inverter's `PV_Power` need not be the real solar. Predbat's docs: point solar at the separate PV inverter's sensor. Another integration reports that on AC-coupled and All-In-One models the registers labelled "PV generation today and total" **count the unit's battery-discharge AC output**, so it renames them "inverter output" there (U12). | No solar reading on the battery inverter is **normal**. The solar wiring accepts another entity. A zero is not treated as "no generation". Divert and forecast accuracy degrade with a clear message. | DATAPOINTS, Predbat docs | **A** |
| SYS-07 | **AC-coupled, firmware under 200** | Battery Pause Mode is added only on AC firmware 200 or later. | The integration does not need it. | Release notes | C |
| SYS-08 | **Single All-In-One, no gateway** | `Power/Power` group, single-phase flows, no PV string values, HV stack values (`Stack_*`), per-slot targets, and AC charge and discharge rate controls (3.6). On this model the solar energy counters may really be battery output (U12). | Capacity and SoC from the right place (the stack). Slot 1 write works. `Charge_Target_SOC_1` versus `Target_SOC` (U8). | DATAPOINTS, release notes | **A** |
| SYS-09 | **All-In-One plus a gateway (not parallel)** | Two GivTCP devices: the All-In-One and a Gateway device with `Gateway_State` and friends. Predbat's docs: with one All-In-One, control the All-In-One directly. | Discovery finds **both** and picks the All-In-One. The prefix order is not assumed. A wrong choice is caught by a check. | Predbat docs, an issue on givenergy-local | **A** |
| SYS-10 | **Parallel All-In-Ones behind a gateway** (2 or 3 units) | **The official GivEnergy API says an All-In-One in a parallel setup is a "child" inverter: it responds to commands but may not change its behaviour.** Another integration found the Gateway's inverter-shaped registers read as zeros, with the real data in Gateway-specific banks, and offers **no controls through a Gateway**. The Gateway device in GivTCP: the `Power/Power` group plus gateway values, `Inverters/AIO_N/...` per unit (`SOC`, `Invertor_Power`, AC energies), `Parallel_Total_*` energies. "For a Gateway, `Battery_Power` and `Invertor_Power` are derived from the combined output of the connected All-in-Ones." GivTCP's README: control only the gateway. A Predbat issue: some gateway entities, notably **battery capacity and the charge and discharge rate**, are not populated. | **Signs, in both directions:** the Gateway's battery power sign was **wrong before 3.6** and is fixed in it, so a fixture from each version gives opposite results. **Which controls exist on the Gateway device** (U9): if the charge schedule, `Target_SOC` or slot controls are absent, the integration refuses to write and says so. **Capacity** from summing the units when the gateway has none. Rates: a clear "unknown", never zero. `Parallel_Total_AIO_Online_Number` lower than `Parallel_Total_AIO_Number` (a unit offline) is shown. | DATAPOINTS, release notes, Predbat issue | **A** |
| SYS-11 | **Three-phase hybrid** (6 to 20 kW, HV batteries) | The `Power/Power` values plus per-phase voltage, current and power, `Meter_Import_Power`, `Meter_Export_Power`, `Battery_Charge_Power`, `Battery_Discharge_Power`. Extra force controls. From 3.6: slots 3 to 10 read, charge and discharge rates added, pause entities removed. Predbat's docs: still compatibility issues. | **`Load_Power` and `Grid_Power` are totals, not one phase** (the reference says three-phase publishes "most of the values above" plus per-phase ones). Sign check on a three-phase fixture. Capacity from an HV stack. The write sequence exists on three-phase: `Enable_Charge_Schedule`, `Target_SOC`, slots. | DATAPOINTS, Predbat docs | **A** |
| SYS-12 | **Two separate inverters** | Each inverter is its own device and prefix. Predbat's docs: they share the house load, and with one supply import and export are the same on each. A shared CT clamp can double count. | The integration asks which one to control. It never adds two. Load and grid are not counted twice. | Predbat docs | **A** |
| SYS-13 | **More than three inverters** | 3.6 has no fixed limit of five. Ports 6345 to 6349 for slots 1 to 5, from 6356 for slot 6 on. | The wizard can list many and ask. | Release notes | B |
| SYS-14 | **Custom device prefix** | The prefix is a setting per inverter (`HADEVICEPREFIX`, `HADEVICEPREFIX_2`, `HADEVICEPREFIX_3`). | Discovery does not assume `givtcp`. Reconfigure's manual choice works. | README | **A** |
| SYS-15 | **Extra PV-only inverter beside the battery inverter** | Not a GivTCP device the integration reads. Predbat's docs: a separate PV-only inverter's generation must be added to the totals. | The solar total does not double count or miss the second array. | Predbat docs | B |
| SYS-16 | **A GivEVC beside the inverter** | A separate device, "GivEVC", enabled by `EVC_ENABLE`. | EV discovery does not mistake inverter entities for a charger, and inverter discovery does not mistake the charger for an inverter (cards GE1 and SY1). | DATAPOINTS | B |
| SYS-17 | **EMS** | Plant-level values only: no plant `SOC`, `PV_Power` or `Load_Power`. Per-inverter `SOC` and `Power`. Controls `Plant_Control` and `EMS_*` slots 1 to 3. "A control that isn't available on your inverter model now says so ('not available for Ems inverters')", including Force Charge and Export. Another integration's notes: an EMS controller's clock cannot be set locally. | Discovery recognises it and the integration **refuses to write**, with a clear message. A managed inverter is never treated as standalone. | DATAPOINTS, release notes | C |
| SYS-18 | **Battery-less or PV-only inverter** | No battery module devices, no usable `SOC`. | "No battery found" and no write. | Library table | C |
| SYS-19 | **Commercial variants, Polar, three-phase AC** | The library marks them **untested**. GivTCP's documents do not describe them. | Recognised as unsupported, or not recognised, with a clear message. | Library table | C |
| SYS-20 | **A 4G dongle, or hardware without local control** | GivEnergy FAQ: some configurations do not support local control. There is no GivTCP. | The integration never sets up. The wizard says GivTCP was not found, as today. | GivEnergy FAQ | C |
| SYS-21 | **Charge slots** | Slots 1 to 10 where the inverter supports them. Per-slot targets on newer Gen 3, Gen 4, All-in-One, HV Gen 3, three-phase. A Homey app listing says Gen 1 and Gen 2 have one charge slot. | Writing slot 1 works on one-slot and many-slot systems. The check for **other active slots** works when slots 2 and above do not exist, and when something else sets them. **`Target_SOC` versus `Charge_Target_SOC_1` (U8).** | DATAPOINTS, release notes | **A** |
| SYS-22 | **GivTCP version pairs** | D.3. | For SYS-05 and SYS-10, a fixture from before 3.6 and one from 3.6. The expected results are written down per version. | Release notes | **A** |
| SYS-23 | **Stale data** | GivTCP republishes the last good data after a failed poll. `Data_Age` is large. `status` can still say online. | No write goes out on stale data (card IB5). The message says why. On versions without `Data_Age`, the limit is documented, not guessed. | DATAPOINTS, release notes | **A** |
| SYS-24 | **Select and time entities for each slot** | From 3.6 and Home Assistant 2026.5, each slot is a select **and** a `time` entity, kept in sync. | We write **one** of them, never both. Both write the same register, and the register write budget matters. | DATAPOINTS, release notes | B |
| SYS-25 | **Child inverters** (an All-In-One in a parallel setup; an AC-coupled inverter beside an EMS) | The official API marks the controller with an `is-controllable` flag. Without it the inverter "will respond to commands but may not change its behaviour when received". GivTCP does not publish that flag. | A write to a child can read back correctly and change nothing. The integration controls the gateway or the EMS-level device only, and says so. It never reports a write as effective on the strength of a read-back alone where the device is a child. | Official API documentation | **A** |
| SYS-26 | **EMS plant mode reasserting settings** | Another integration reports that an EMS controller periodically reasserts some inverter settings, so writes succeed, hold briefly, then revert within minutes. | The target reverts after our write. The Charge Target Conflict sensor (CC3) can fire, and the wording covers it. We never fight the controller by writing again and again. | givenergy-hass troubleshooting | C |
| SYS-27 | **Two energy sets** | Another integration notes two coexisting energy sets: battery (DC) charge and discharge, and AC-side charge and discharge, with conversion losses between. On sites with a GivEnergy EV charger the AC-side charge figure includes EV charging energy. | Which counter we read for "grid energy into the battery" and for battery cost. An EV charger on the same site does not inflate the battery's cost figures. | givenergy-hass README | B |
| SYS-28 | **Firmware-gated values** | Another project documents registers that read zero on older firmware, and the same address meaning different things on different firmware lineages. Firmware numbers are not comparable across families. | A zero counter on an older inverter is treated as "not provided", not as zero energy. Anything that depends on a value (solar share, battery totals) says so when the source is zero by firmware. | givenergy-modbus `hardware-firmware-quirks.md` | B |
| SYS-29 | **Ghost slots** | A battery or meter that responds but reads all zeros is not a device. Detection drops it. | An all-zero module is not counted in the battery count or capacity. | givenergy-modbus detection | B |
| SYS-30 | **Unit change at upgrade** (Gateway energy totals, 3.5 to 3.6) | Totals were published in MWh labelled kWh and are now kWh, so a total goes from about 12.68 to 12,682.7 in one step. | An accumulator that reads these totals does not book the step as energy. Any counter step larger than the inverter could deliver in the elapsed time is a baseline reset, logged once. | GivTCP 3.6 release notes | **A** |
| SYS-31 | **Entity sets change at upgrade** | HV Gen 3 hybrids move to the single-phase set and the old entities are removed. AC and All-in-One lose the PV string entities. Battery BMS Current becomes Battery Pack Current. | A configured entity disappears. The integration re-detects, raises a repair that names what changed, and re-maps by suffix on confirmation. It never switches controller silently. | GivTCP 3.6 release notes | **A** |
| SYS-32 | **Battery-only child devices** | With "Only report battery data and controls" set, inverters behind an EMS or Gateway publish only battery data and controls. | Whole-house values come from the Gateway or EMS device. A role is never read from a device that does not publish it. | GivTCP 3.6 release notes | **A** |
| SYS-33 | **Inverter stops responding** | GivTCP pauses sending (`status` is `paused`), recovers with a fresh connection, and answers REST writes with "not sent". `Data_Age` grows. | `paused` and a large `Data_Age` both mean not publishing. No write is attempted. Normal operation resumes when `status` is `online` and `Data_Age` is small. | GivTCP 3.6 release notes, datapoints | **A** |
| SYS-34 | **Clock out by 5 minutes or more** | GivTCP warns. Today counters reset at the wrong time and the charge window runs on the wrong clock. | Readiness warning when `Invertor_Time` differs from Home Assistant time by 5 minutes or more. We do not set the clock. | GivTCP 3.6 release notes, datapoints | B |
| SYS-36 | **Stale "today" counters after midnight** (older versions) | Today stats could keep yesterday's value after midnight. | Daily figures do not depend on a "today" counter resetting at midnight on versions older than 3.6. | GivTCP 3.6 release notes | B |
| SYS-37 | **Entity ids reset** (GivTCP 3.6 and 3.6.1) | Changed discovery configs were deleted and recreated, so renamed or 2.x ids went back to GivTCP's default and lost names, areas and icons. Temperature sensors were recreated on every restart. Fixed in 3.6.2. | A configured entity id that disappears is found again by the entity registry's unique id. If it cannot be found, one repair names what is missing. No silent switch. | GivTCP 3.6.2 changelog | **A** |
| SYS-38 | **Charge slot 2 registers** (GivTCP 3.6.0 only) | On 10-slot inverters slot 2 was read and written at the wrong registers. Fixed in 3.6.1. | The other-schedule check does not report a phantom or missing slot 2 on 3.6.0. We write slot 1 only, so charging is unaffected. | GivTCP 3.6.1 changelog | B |
| SYS-39 | **PV-only inverter on 3.6.0** | Every poll failed on a missing energy total. Fixed in 3.6.1. | The device is treated as not publishing, not as zero solar. | GivTCP 3.6.1 changelog | B |

#### D.5 Cross-cutting cases (every fixture runs these)

1. **Signs** against `test_reads_grid_power_negative_when_exporting` and `test_reads_battery_power_discharging`. Prove it per configuration **and per version**. The Gateway proves signs are not constant.
2. **A missing value is never zero.** If capacity, rate or solar is absent, say so and degrade. Never plan on zero.
3. **Dry run:** nothing is sent to any configuration when it is on.
4. **Write budget:** the register write count rises by the writes sent and by no more. GivTCP publishes its own `Write_Count`. A test may compare them.
5. **Availability and staleness:** unavailable, back, and stale (SYS-23).
6. **Reconfigure:** choosing the entities by hand works for each.
7. **Prefix and serial:** never assume the prefix is `givtcp`, or that the first device found is the right one, or that a serial is upper or lower case. Predbat's own documentation says its serial must be entered in lower case.
8. **Which charge target governs (U8).** On every inverter with per-slot targets, prove that the write sequence's `Target_SOC` plus `Enable_Charge_Target` stops the charge at the target. **This needs a real charge**, not only a fixture. If it does not, the sequence needs `Charge_Target_SOC_1`, and that is a change to card IB4, not a footnote.
9. **An upgrade of GivTCP that renames entities** produces the "entities missing" repair, and Reconfigure recovers.

#### D.6 Fixtures to collect, in order

1. SYS-10 (parallel All-In-Ones with a gateway), from **two** GivTCP versions if possible.
2. SYS-09 and SYS-08 (All-In-One with a gateway, and alone).
3. SYS-11 (three-phase).
4. SYS-05 (Hybrid HV Gen 3), before and after 3.6.
5. SYS-02 (hybrid with several batteries), one pack and several.
6. SYS-06 (AC-coupled).
7. SYS-12 (two inverters) and SYS-14 (custom prefix).
8. SYS-04 (a Gen 2 owner) if one can be found.

**Cross-check each fixture with the hardware's own view.** The `givenergy-cli` tool can write a redacted register dump (`givenergy-cli --host <ip> export -o plant.json`, serial numbers redacted by default), and the givenergy_local integration has a capture action. Neither gives GivTCP entity ids, but the dump names the real model and topology, so a fixture cannot be mislabelled. Ask owners for it when they are willing. It is read-only by default.

**For each fixture:** every entity id, state, unit and attributes from Developer Tools, plus `GivTCP_Version`, `Invertor_Type`, `Invertor_Max_Inv_Rate`, `Invertor_Max_Bat_Rate`, `Battery_Capacity_kWh`, `Battery_Capacity_kWh_calc`, `Data_Age`, the number of battery modules, and which charge slot and target entities exist. Anonymise serials in a way that keeps the pattern. Remove IP addresses and names.

#### D.7 GivTCP 3.6, 3.6.1 and 3.6.2 (all released 11 October 2026): what changed and what it settles

Source: the release notes and the 3.6 `docs/DATAPOINTS.md`, `docs/SETTINGS-GUIDE.md`, `settings.json`. GivTCP 3.6 now uses the published givenergy-modbus library (version 2), detects each inverter's model and devices once and saves them, and detects again if the saved details stop matching.

| Fact | Consequence for this integration |
|---|---|
| **Gateway energy totals were published in MWh labelled kWh and are now kWh**, so they jump 1000 times once on upgrade | Accumulators must not book a 1000 times step as energy (SYS-30, card SY4) |
| **HV Gen 3 hybrids** are now single-phase; their entity set changes and the old entities are removed | Configured entities can vanish on upgrade: re-detect, repair, re-map (SYS-31, SY4) |
| **AC and All-in-One:** PV string voltage, current and power entities are removed; `PV_Power` (the total from the PV inverter) remains | Do not read string values on those models. U12 narrows to the energy counters |
| **Battery BMS Current** renamed **Battery Pack Current**, and read 0 A wherever the firmware does not report it | A zero is not a reading (SYS-28) |
| **"Only report battery data and controls" now takes effect.** Inverters behind an EMS or Gateway then publish only battery data and controls | Whole-house values come from the Gateway or EMS device; per-unit devices hold battery data (SYS-32) |
| **Gateway:** controls that failed now work; charge and discharge rates and per-slot target SOCs exist on it; battery, inverter and Liberty power signs are fixed | U9 mostly answered. Version policy: sign correction only below 3.6 |
| **Per-slot charge and discharge target SOC** on 10-slot inverters, three-phase and the Gateway. `Enable_Charge_Target` on stops at `Target_SOC`, off charges to 100 percent | U8 partly answered (card SY1 capability probe) |
| **Force Charge did nothing on 10-slot inverters when the SOC was above slot 1's target** (fixed) | Slot 1's target matters on those inverters |
| **Battery Pause Mode** (`Disabled`, `PauseCharge`, `PauseDischarge`, `PauseBoth`) applies **during the pause timeslot**. Available on Gen 1 (firmware 187 or later), Gen 2, Gen 3, HV Gen 3, All-in-One, Gateway and AC (firmware 200 or later) | Pre-flight: paused only when the mode blocks charging **and** the time is inside the pause slot |
| **Pause When Inverter Stops Responding** (per inverter, off by default): GivTCP sends nothing for a while and `status` shows `paused`; REST writes get an immediate "not sent" | Treat `paused` as not publishing; no writes (SYS-33) |
| **`Data_Age`, `Time_Since_Last_Update`, `status`, `GivTCP_Version`, `Invertor_Type`, `Invertor_Time`** are sensors | U10 answered |
| **Power flow entities on every model** (single-phase, three-phase, Gateway; PV-only inverters only the two solar flows), non-negative and never above the load | A normalised source for surplus decisions (Part B 1.5.2) |
| **Warning when the inverter clock is 5 minutes or more out**; `Sync_Time` button; `Sync Time` could previously set the clock an hour out | Clock drift is readable (SYS-34, Part B 1.5.8) |
| **Today energy stats** (load, self consumption, day and night cost) could stay on yesterday's value after midnight (fixed) | Do not rely on "today" counters resetting on older versions (SYS-36) |
| **Multi-inverter setups** could show an inverter as the wrong model (fixed); no limit of five inverters; config page in the sidebar | Classification must not assume one prefix |
| **Shipped defaults:** `day_rate` 0.395, `night_rate` 0.155, `export_rate` 0.04, rate starts 05:30 and 23:30, `Smart_Target` false, PALM winter months 01 02 03 10 11 12, shoulder 04 05 09, PALM minimum target 25, maximum 45, reserve 4, utilisation 0.85, weight 35 | RA2 skips these. They also match SPEC-001's inputs |
| **3.6.2 (about 4.5 hours after 3.6): GivTCP deleted and recreated any Home Assistant entity whose discovery config had changed, which reset its entity id to GivTCP's default.** Renamed ids and older ids were reset and lost their names, areas and icons. A comparison bug also recreated every temperature (°C) sensor on every restart. Fixed in 3.6.2; ids already reset on 3.6 or 3.6.1 stay reset until changed back by hand | **3.6 and 3.6.1 are unsafe for any integration that stores entity ids.** Resolve entities by registry unique id, not only by stored id (SYS-37, SY4). Treat 3.6.2 as the first safe 3.6 |
| **3.6.1: charge slot 2 on 10-slot inverters** (newer Gen 3, Gen 4, HV Gen 3, All-in-One, Gateway) was written to and read from the wrong registers in 3.6, so it could not be set and read back wrong. Fixed in 3.6.1 | Any read of slot 2 (the other-schedule repair) is wrong on 3.6.0 (SYS-38) |
| **3.6.1: PV-only (string) inverters** returned no data in 3.6, every poll failing on a missing energy total. Fixed in 3.6.1 | A PV-only device on 3.6.0 is not publishing (SYS-39) |
| The add-on file in the 3.6 tag still shows version `3.5.68` | **Do not trust the version string alone.** Read `GivTCP_Version` on a real 3.6 instance, and classify by entities first |

### Appendix E. How other systems handle GivEnergy configurations

**Purpose:** approaches and warnings from other projects, to be turned into specifications (Part C (specifications)) and then built by our own code. **Specification first, never copy** (rule 16). Facts below come from each project's own README, release notes or documentation, read in October 2026. None was run.

#### E.1 Systems reviewed

| System | Route | Configurations it names | How it handles them | Lesson |
|---|---|---|---|---|
| **GivTCP** (britkat1980's fork of GivEnergy's `giv_tcp`) | Local Modbus to MQTT | Hybrid, AC-coupled, single and three-phase, Gateway, EMS, GivEVC, All-In-One | Appendix D | The communication layer we use |
| **givenergy-hass** (dewet22, domain `givenergy_local`) | Local Modbus. **No GivTCP, no MQTT broker.** | Single and three-phase hybrid, AC-coupled, All-In-One, EMS, Gateway | **Hardware detection at first run**, the plant topology cached, an action to **re-detect** after a battery is added or removed, battery count probed from the bus with no manual override. Per-module devices for All-In-One. A controller device for EMS. A Gateway device **with no controls offered**. Entities are **gated by model**. | Detect once, cache, offer a re-detect. Model-gating is normal. |
| **givenergy-modbus** (dewet22, library) | Local Modbus | Hybrid Gen 1 and Gen 3, AC, All-In-One, three-phase, EMS, Gateway: validated. Hybrid Gen 2, Polar, commercial All-In-One and EMS, three-phase AC: **untested** | A published, **evidence-based support table**: validated means pinned by tests against wire captures from real hardware. | Copy the honesty: say validated or untested per configuration. |
| **givenergy-cli** (dewet22) | Local Modbus | Same library | Read-only by default. Probe, capture, export a redacted plant dump, mock server. States that the local interface is unauthenticated and unencrypted. | A way to learn a fixture's true model and topology. |
| **givenergy-local** (cdpuk) | Local Modbus | Originally hybrid. An issue records that an All-In-One has **two IP addresses**, one for the inverter and battery and one for the gateway, and was not supported. | A paused project that embeds a fork of the library. | Older projects did not handle All-In-One at all. |
| **Predbat** | Local via GivTCP, or the GivEnergy cloud | Single and multiple All-In-One, gateway, three-phase, two or three inverters | Configured by hand. Its **cloud** mode auto-configures and has settings for the awkward cases: **shared CT clamp** (inverters sharing one meter, so grid and load are not added twice), **split CT**, **PV-only inverters**, duplicate meter serials. | These are the multi-inverter traps to test (SYS-12, SYS-15). |
| **GivEnergy cloud API v1** (official) | Cloud. The communication-device list is marked "subscription required". | Hardware list: Gen 3 **PV-only string inverters** (`GIV-PV-3.6-G3` to `GIV-PV-6.0-G3`), Commercial EMS, Plant EMS, EMS-R, EMS-C, Gateway, All-In-One (`GIV-AIO-AC-13.5-3.6`, `GIV-AIO-AC-13.5-5.0`) | An **`is-controllable` flag**: absent on child inverters, which "respond to commands but may not change their behaviour". | Not every inverter accepts control (SYS-25). PV-only string inverters exist. |
| **Homey GivEnergy app** | Local | Hybrid and others; actions for charge slots | Its listing says Gen 1 and Gen 2 support one charge slot. | One-slot systems (SYS-21). |
| **Smart Immersion Heater Booster** (a personal script) | GivEnergy and myenergi **cloud** APIs, run by cron | One GivEnergy 5 kW inverter and battery, one myenergi Eddi | Boosts the immersion for a period set by the battery's charge, using surplus battery charge only. | A precedent for battery-aware immersion heating. It is cloud-based and tied to one install. |
| **PALM** (standalone, salewis38) | GivEnergy cloud | One inverter | Sets the overnight target, and has "a simple sequencer for load management, based on time, temperature, battery charge and CO2/kWh" for switched loads. | Load switching with temperature has a precedent. |
| **evcc, openHAB, EMHASS, Solar Assistant** | | | **Not reviewed.** A search found no GivEnergy support in them. That is not proof there is none. | |

#### E.2 What the other systems learned that we should test or copy as ideas

1. **Detect the topology once, cache it, and offer a way to re-detect.** givenergy-hass does it and adds an action for after a battery change. Our wizard reads capacity at setup. Read the capacity live (config diet follow-up 1), and make the "entities changed" path obvious (SYS-05, D.5 item 9).
2. **Model-gated entities are normal.** An absent value is not zero. givenergy-hass suppresses "house consumption today" on All-In-One and EMS, and puts the whole-house energy figures on the Gateway device. Every read in this integration needs an "absent" path (D.5 item 2).
3. **A Gateway device is not an inverter.** givenergy-hass found its inverter-shaped registers read as zeros and offers **no controls through a Gateway**. The official API says a child inverter ignores commands. Together these make U9 the question that decides whether we can write on a parallel All-In-One system at all.
4. **Solar counters may not be solar.** On AC-coupled and All-In-One models the "PV generation" registers count battery-discharge AC output (U12). Our forecast accuracy and solar-share figures read them.
5. **Two energy sets coexist** (DC battery and AC side), and EV charging is inside the AC-side charge figure (SYS-27).
6. **An EMS reasserts settings.** Writes revert within minutes. Do not fight it (SYS-26, CC2).
7. **Publish health, and use it.** givenergy-hass exposes consecutive refresh failures, last successful refresh, reconnects and dongle hangs. GivTCP has `Data_Age` and `Time_Since_Last_Update`. Use them (card IB5).
8. **Concurrent local clients are reported to work.** givenergy-hass says its integration and GivTCP can poll the same inverter at once, and attributes earlier conflicts to retry and recovery behaviour in an older shared library, not to the inverter. It also offers an optional **passive mode** that reads the cache another client keeps fresh. **This contradicts a guide that says never to run two clients at once.** It does not change this release, because we read GivTCP's entities, not the inverter. It matters if a direct backend is ever built.
9. **State support honestly, per configuration.** Copy the validated or untested table (SY3).
10. **Make fixtures cheap to collect.** A redacted dump (`givenergy-cli export`) and a capture action exist. Use them to label each fixture (D.6).

#### E.3 Peers to know about

- **givenergy-hass is a local-Modbus alternative to GivTCP.** If a second backend is ever added behind the interface in section 5, it is the most likely one. It exposes the controls we use under its own names (Enable Charge, Charge Target SOC, charge slot start and end as `time` entities), **deliberately omits slots 3 to 10**, and offers none through a Gateway. It cannot run beside the older cdpuk integration, which shares its domain.
- **Energy Conductor** (same author, early days, separate project) is an entity-driven, technology-agnostic coordination layer for Home Assistant. Its README shows a plan "in plain English" with reasoning and control status, a cost and savings ledger, and a tape of 12 hours of history and 12 of forecast with scheduled events (off-peak, EV, solar diversion). It overlaps with the pitch of this integration. The maintainer should know it exists. It was not evaluated here.
- **Predbat's generator.** givenergy-hass generates a starting Predbat `apps.yaml` for single hybrid, AC-coupled and EMS plants, and says multi-inverter, three-phase and Gateway plants are not templated yet. The same configurations are the hard ones everywhere.

### Appendix F. Roadmap changes from the competitor review (card RM1)

Source analysis: Part D (gap analysis). The text below is what to add to `ROADMAP.md`. Table columns follow the roadmap: **Item | What and why | Evidence | Indicative value per year | Size**. Sizes are the roadmap's: S a day or less, M two to four days, L a week or more.

#### F.1 New items

**Should have, Setup and delivery**

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **S19 Add an action that exports an anonymised system profile** | An action that writes a redacted list of the inverter's entities (ids with serials replaced, states, units and attributes), the GivTCP version, the inverter type, the number of battery modules and which charge slots exist, then shows a notification with a download link. Users attach it to an issue. It makes every inverter configuration testable without screenshots, and it is how support for All-In-One, gateway, three-phase and EMS systems gets proved on real hardware | givenergy-hass has a capture action and givenergy-cli can export a redacted plant dump (serial numbers redacted by default) ([givenergy-hass](https://github.com/dewet22/givenergy-hass), [givenergy-cli](https://pypi.org/project/givenergy-cli/1.5.0/)) | Not applicable | M |

**Could have**

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **C28 Add an away mode** | A switch, or a number of days away, that stops away days from being learned as normal load and lets the plan recover afterwards. Today a week away fills the learned profile with low-load days, so the plan under-charges for several days after you return. Predbat matches load history by holiday state, so a day at home is predicted from days at home | Predbat: [holiday mode](https://springfall2008.github.io/batpred/customisation/#holiday-mode) and [`days_previous_auto`](https://springfall2008.github.io/batpred/apps-yaml/). Behaviour specified in `docs/design/specs/` (SPEC-003): away days matched per sample, a fallback scale for the first day away and the day home, a drop-the-lowest-day filter | Not measured (low) | S |
| **C29 Read the battery capacity live** | Take the capacity from GivTCP on every cycle (`Battery_Capacity_kWh`, or the module-based `Battery_Capacity_kWh_calc`) so adding a module or an ageing battery needs no visit to Configure. Check which of the two matches the usable energy on each system type | The config diet review (`docs/design/CONFIG_DIET.md`, follow-up 1). GivTCP [datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md). givenergy-hass probes the battery count at start-up and offers a re-detect action | Not applicable | S |
| **C30 Offer an action that exposes a recommended set of entities to Assist and LLM tools** | Home Assistant does not expose `power`, `energy` or `battery` sensors to voice assistants by default, so "what is my battery at?" returns nothing until they are exposed. An idempotent action that only ever exposes (never un-exposes) the headline sensors. Do not ship aliases: the registry cannot tell ours from the user's | givenergy-hass has one ([README](https://github.com/dewet22/givenergy-hass)). Background: [community thread](https://community.home-assistant.io/t/wth-are-all-new-entities-exposed-to-assist-by-default/803889) | Not applicable | S |
| **C31 Set the charge mode of Wallbox, OCPP, Ohme and Easee chargers** | The EV code finds five brands but sets only the Zappi's mode. Map the logical "use surplus only" to each brand's option. Never stop, pause or fast charge, as the safety rules say. Needs an owner of each brand to supply entity lists first. The GivEnergy charger arrives in v0.19, and its import cap and session cap are candidates here | Predbat starts and stops a Zappi, an Ohme and a GivEnergy charger from its car plan ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/)). GivTCP's GivEVC controls ([datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)) | Not applicable | M |
| **C32 Say when the Solcast P10 attribute is switched off** | The pessimistic forecast reads the `estimate10` attribute of the Solcast tomorrow sensor. Solcast lets users switch that attribute off, and the integration then has no pessimistic estimate and says nothing. Detect a Solcast forecast sensor with no `estimate10`, and show it in diagnostics or as a repair with the setting to change | Solcast README: [sensors and attributes](https://github.com/BJReplay/ha-solcast-solar) (options `attr_brk_estimate10` and `attr_brk_hourly`). The attribute is read in `coordinator.py`. Check the default first (card FS1) | Not applicable | S |
| **C33 Document and test two more forecast sources** | Open-Meteo Solar Forecast is free, needs no account, and has `watts` and `wh_period` attributes (a tomorrow energy sensor is likely but not confirmed). Helios Forecast learns from the user's own production and offers an action `helios_forecast.get_forecast`. Both are common choices for people without a Solcast account. Confirm each exposes a usable tomorrow sensor, add them to the wizard's suggestions and the docs, and note what each does about dampening and shading | [Open-Meteo Solar Forecast thread](https://community.home-assistant.io/t/open-meteo-solar-forecast/733073), [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast), [Solar Forecast Card](https://github.com/AshGSmith/solar-forecast-card) (lists the supported providers) | Not applicable | S |
| **C34 Offer cheap-period sensors for the user's own automations** | A binary sensor that is on during the cheapest window, and one for the cheapest N hours between two times, so a dishwasher or a heat pump can follow the tariff without a template. Check which of these already exist before adding any. The Octopus Energy integration's target rate sensors are described by its author as one of its key features, and he is moving them into a separate data-source-neutral integration | [Octopus Energy target rate discussion](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/discussions/1305), [target rate sensors in use](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/discussions/284). PV Excess Control has tariff integration ([README](https://github.com/InventoCasa/PV-Excess-Control)). The selection rules (continuous and intermittent, ties, limits, weighting) are specified in `docs/design/specs/` (SPEC-006) | Not applicable | S |

**Nice to have**

| Item | What and why | Evidence | Indicative value per year | Size |
|---|---|---|---|---|
| **N19 Show per-module battery health** | GivTCP publishes each battery module's state of charge, capacity, cycles and temperature, and for high-voltage stacks the state of health and cell voltages. Start with the module list and the stack's state of health. Needs C17 | GivTCP [datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md). givenergy-hass shows per-cell voltage and temperature with a heat map card ([README](https://github.com/dewet22/givenergy-hass)) | Not applicable | M |
| **N20 Add a Glance view and a wall-panel view** | One sentence for the system's state, three large numbers and a few health pills, with no tabs, for a wall tablet or a phone. Built from core cards | givenergy-hass has flow, glance, analyst and kiosk modes ([README](https://github.com/dewet22/givenergy-hass)) | Not applicable | M |
| **N21 Raise the reserve ahead of a severe weather alert** | Keep the battery fuller when an alert is active. **Read first** how Predbat's weather alert system works and which alert source is trustworthy for each country. Nothing was read beyond its name | Predbat lists a "Weather Alert System" in its [apps.yaml documentation](https://springfall2008.github.io/batpred/apps-yaml/) | Not measured (low) | M |
| **N22 Charge in a second cheap window** | Some tariffs have two cheap periods a day, for example an afternoon one. Needs an inverter with a second charge slot (a Homey app listing says Gen 1 and Gen 2 have one) and a target rule for each window. Related to C26 | PALM added an afternoon Cosy charge period ([PALM](https://github.com/salewis38/palm)). [Homey app listing](https://homey.app/en-gb/app/io.jak.givenergy/) | Not measured (low) | L |
| **N23 Add a second inverter backend using direct local Modbus** | After the backend interface in v0.19, a second backend would remove the GivTCP add-on and its MQTT broker for people who do not run them, and is a way to keep working if GivTCP stops being maintained (see C23). The candidate is givenergy-hass (local Modbus). It exposes enable charge, charge target SOC and slot times, leaves out slots 3 to 10, and offers no controls through a Gateway. It reports that two local clients can poll one inverter. Write a new adapter from the interface. Copy no code. Needs fixtures for each system type | [givenergy-hass](https://github.com/dewet22/givenergy-hass), [givenergy-modbus](https://github.com/dewet22/givenergy-modbus) (supported-hardware table), [givenergy-cli](https://pypi.org/project/givenergy-cli/1.5.0/) | Not applicable | L |
| **N24 Correct the solar forecast by matching similar past conditions** | Instead of one daily accuracy ratio, look up past days (or hours) whose forecast conditions were similar and read what the installation actually produced then, as a ratio to the forecast. The median ratio gives a site-specific correction and the 10th and 90th percentile ratios give a data-driven band. Blend back to the plain forecast when few similar days exist. Needs the production and forecast history the integration already keeps, and ideally a weather source. Specified in `docs/design/specs/` (SPEC-009) | Helios Forecast does this per hour with a physical model ([repository](https://github.com/ReikanYsora/Helios-Forecast)) | Not measured (low) | L |

#### F.2 Existing items: append this to the Evidence column, or rewrite as shown

| Id | Change |
|---|---|
| **C22** | Append: "Predbat takes several arrays as a list in its forecast settings ([apps.yaml](https://springfall2008.github.io/batpred/apps-yaml/))." |
| **C23** | **Rewrite What and why:** "GivEnergy Ltd entered administration on 9 April 2026 and ceased trading. The software company that runs the cloud is separate. Its free tier keeps local control and third-party software on the home network, and moves remote access, history and automation such as Smart Tariff into a paid Premium tier ([FAQ](https://givenergy.cloud/givenergy-faq)). What is left: schedule the existing `export_energy_data` action for backups, document moving to another inverter brand, and plan a second backend that does not need GivTCP (N23)." **Evidence:** "`REQUIREMENTS.md`, non-goals. [Administrator's statement](https://daily-focus.co.uk/2026/04/givenergy-ceases-trading-with-all-jobs-lost/)." |
| **C24** | Append: "In v0.19 the months become settings with defaults from the latitude." |
| **C25** | Append: "Predbat tunes inverter loss and battery loss, around 4% each for a hybrid ([configuration guide](https://springfall2008.github.io/batpred/configuration-guide/))." |
| **N12** | **Rewrite What and why:** "Use the forecast provider's per-period attribute instead of a fixed bell curve (in v0.19, where the provider exposes one). Dynamic day-ahead tariffs still need a verified source first." Append evidence: "Predbat reads rates and the standing charge from the Octopus Energy integration ([energy rates](https://springfall2008.github.io/batpred/energy-rates/)). The GivEnergy Tariff Optimiser add-on schedules charge slots on Agile ([post](https://community.home-assistant.io/t/givenergy-tariff-optimiser-automated-octopus-agile-battery-scheduling-arbitrage-add-on/1021514))." |
| **N13** | Append: "evcc plans charging to a departure time, varies it on surplus and battery state ([roundup](https://diyai.io/ai-tools/engineering/best-ai-home-energy-management-tools/)). Predbat has a [car charging plan](https://springfall2008.github.io/batpred/car-charging/). The slot-selection and fallback rules are specified in SPEC-008." |
| **N14** | Append: "Predbat's [plan card](https://springfall2008.github.io/batpred/predbat-plan-card/) shows rate, status, limit, forecast solar, load, car and diverter energy per slot. Energy Conductor shows twelve hours of history and twelve of forecast on one axis ([README](https://github.com/dewet22/givenergy-hass))." |
| **N8, C17** | Append: "GivTCP publishes stack state of health and per-module values ([datapoints](https://github.com/britkat1980/giv_tcp/blob/3.6.0-beta1/docs/DATAPOINTS.md)). See N19." |
| **N3, N11** | Append: "v0.19 finds All-In-One, gateway, three-phase and several inverters and says which were tested on real hardware. Known traps are in the design notes in `docs/design/`: a parallel All-In-One is a child inverter that may ignore commands (the [official API](https://givenergy.cloud/docs/api/v1)), a Gateway offers few or no controls, and an EMS plant reasserts settings. Detection, gating and caching of system types are specified in `docs/design/specs/` (SPEC-005)." |
| **Won't have: the copying row** (Predbat, PV Excess Control, `ecodan_ctrl`, OpenEMS) | Rewrite What: "Copying code, comments, names or structure from other projects." Why: "We build our own. Studying how they work and writing our own specification, then building from it, is allowed. The specification contains no code." |
| **Won't have: the optimiser row** (linear programming, machine learning, EMHASS, EOS) | Append to Why: "evcc's own optimiser is described in its documentation as informational only and does not yet control the home battery ([evcc optimiser](https://docs.evcc.io/en/features/optimizer.md)). EMHASS needs a solver and a trained model to maintain ([documentation](https://emhass.readthedocs.io/))." |
| **N1** | Append: "PALM's load sequencer switches loads on time, temperature, battery charge and CO2 per kWh ([PALM](https://github.com/salewis38/palm))." |
| **S5** | Append: "A simple open-source script charges a home battery overnight only if tomorrow's solar will not cover the day, or if the battery is nearly empty ahead of an expensive morning ([Charge-battery](https://github.com/mhurk/Charge-battery)). That is the same two cases this item targets." |
| **S17, N7** | Append: "The Octopus Energy integration can track the cost of any other entity and compare it with another tariff ([repository](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)). PV Excess Control tracks savings, the self-consumption ratio and energy statistics ([README](https://github.com/InventoCasa/PV-Excess-Control))." |
| **C19** | Append: "OpenEVSE's Home Assistant integration uses a claim and override system, so several callers can queue, override or limit a charge safely ([README](https://github.com/firstof9/openevse)). PV Excess Control offers three battery strategies: battery first, appliance first and balanced ([README](https://github.com/InventoCasa/PV-Excess-Control)). Shedding order and the three battery protections are specified in SPEC-007." |
| **C18** | Append: "PV Excess Control sheds appliances when the battery falls below a minimum and allows a small amount of grid power to top up a load ([README](https://github.com/InventoCasa/PV-Excess-Control)). Behaviour is specified in `docs/design/specs/` (SPEC-007): an averaged surplus gates turn-on and an instantaneous one gates shedding, with a minimum count of good samples and an off threshold." |
| **N4** | Append: "A community project sizes an overnight immersion top-up from tomorrow's forecast and adds weather compensation from the outside temperature, heating to the maximum when the previous day's solar top-up was low ([thread](https://community.home-assistant.io/t/smart-immersion-heating-for-domestic-hot-water/536281)). EMHASS models a water tank as thermal storage ([documentation](https://emhass.readthedocs.io/))." |
| **C31** | Append: "evcc connects chargers through templates for OCPP, Modbus and HTTP ([repository](https://github.com/evcc-io/evcc)). OpenEVSE has a solar divert mode ([README](https://github.com/firstof9/openevse))." |
| **S1** | Append: "v0.19 adds a dashboard warning when something else sets the charge target. PALM's SmartTarget, Predbat and the GivEnergy app can all do it, and an EMS plant reasserts its own settings." |
| **S4** | Append: "Predbat's [iBoost model](https://springfall2008.github.io/batpred/customisation/) has a daily energy cap, a minimum SoC and a gas price scale. A personal script boosts an immersion for a time set by the battery's charge ([Smart Immersion Heater Booster](https://github.com/robkwhitehouse/Smart-Immersion-Heater-Booster)). The diverter's per-step rules (price test, daily cap, minimum power, minimum state of charge) are specified in SPEC-004." |

#### F.3 Won't have for now: add these rows

| Decision | Why |
|---|---|
| Variable-power immersion diversion (a dimmer or phase-angle controller) | Needs special hardware. The integration switches a plain switch, and hardware diverters (iBoost, Eddi) already vary the power |
| Uploading to PVOutput, and a general time-and-temperature load sequencer (PALM) | Not asked for. Long-term analysis is covered by Home Assistant statistics and the Energy dashboard |

#### F.4 Known limitations: add these rows

| Limitation | Impact | Tracked as |
|---|---|---|
| Tested on one single-phase hybrid | All-In-One, gateway, three-phase, EMS and several-inverter systems are found but not proved on real hardware | N3, S19 |
| A parallel All-In-One is a child inverter and a Gateway may offer no controls | A write can read back correctly and change nothing. The integration controls the gateway or the plant device only | N3, N23 |
| On AC-coupled and All-In-One systems the solar energy counters may count battery output | Forecast accuracy and solar share could read high. Not yet verified | N11 |
| The immersion is switched on and off, never varied | A small surplus may be partly met from the battery or the grid | Won't have |
| One charge window | A second cheap period is not used | N22 |
| An away period fills the learned load with low days | The plan under-charges for several days after you return | C28 |

#### F.5 Open questions: add these

3. **Which GivTCP versions are supported?** GivTCP 3.6 changed signs, entity sets and pause entities. The release supports what its fixtures prove.
4. **On inverters with per-slot targets, does `Target_SOC` stop a charge?** The write sequence assumes it does. A real charge on such an inverter settles it.


---
