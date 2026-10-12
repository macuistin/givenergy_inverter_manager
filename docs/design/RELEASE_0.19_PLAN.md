# Release 0.19: the plan against the code

Written on 12 October 2026 against `main` at v0.18.1. The brief was written against v0.18.0. This page says what the brief gets wrong or leaves open now, how the cards are grouped into pull requests, what is blocked, and what the maintainer has to supply. No code is written yet.

The documents it works from:

- [RELEASE_0.19_BRIEF.md](RELEASE_0.19_BRIEF.md): goal, decisions, guardrails, every card, the configuration test matrix.
- [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md): designs for the roadmap features. None is built in 0.19 unless named.
- [specs/](specs/README.md): the specification method and the specifications from other projects.
- [RELEASE_0.19_AGENT_NOTES.md](RELEASE_0.19_AGENT_NOTES.md): how the work is run.

## 1. What 0.19 is

GivTCP stays the only backend but becomes a communication layer behind one small interface. The integration owns the rates, retries a missed charge write, re-plans inside the cheap window, uses the forecast's own shape, makes the seasonal rules settings, warns when something else sets the charge target, supports the GivEnergy EV charger, and finds more system types than one single-phase hybrid. Part A section 1 lists what is out of scope: a direct Modbus backend, dynamic tariffs, export or discharge logic, a second charge window and a new dashboard layout.

## 2. What changed after the brief was written

The brief names v0.18.0 (`461c5fc`) as its base. `main` is now v0.18.1. Two of its changes overlap cards in the brief.

| 0.18.1 change | What it does | Cards it touches | What to do |
|---|---|---|---|
| A repair when a charge write is not taken (`core/write_confirmation.py`, `unconfirmed_write_repair.py`, repair `write_not_confirmed`) | After the writer's retries read back the old value, one repair lists the settings that did not take. The writer still returns success, so the caller carries on | IB3, IB4 (the writer moves), WS1 (what counts as a failed write), RU2 (safety rule wording) | Move the confirmation listener with the writer. Decide the retry question in section 3, item 2 |
| A frozen-feed check (`GIVTCP_FROZEN_AFTER_S` = 600, `_require_feed_moving`, repair `givtcp_feed_frozen`) | If none of solar, SoC, battery power, grid and load has been reported for 10 minutes, the cycle fails, entities go unavailable, the nightly write is skipped and a repair appears | IB5 (`is_publishing()`), SYS-23 and SYS-33 in Appendix D, RU2 | Move it behind `is_publishing()` and add the brief's checks to it. See section 3, item 1 |

Also new since the brief: the Docs entry for GivTCP's Real Time Control in `docs/troubleshooting.md`, the date pin in the forms golden, and the 0.18 progress file now being out of date (every 0.18 card is merged, and `PROGRESS.md` still says "none yet").

## 3. Where the brief and the code disagree

Each item says what I propose. None blocks the cards that can start now unless it says so.

1. **Staleness (IB5).** The brief wants `is_publishing()` to read `Data_Age` and `status`. The code already has a frozen-feed check built on `State.last_reported`, which works on GivTCP 3.5 and 3.6 alike. `Data_Age` does not exist on older GivTCP. Proposal: `is_publishing()` is true only when all of these hold: `status` is not `paused` (where it exists), `Data_Age` is below the limit (where it exists), and the existing `last_reported` rule is satisfied. Where `Data_Age` is missing the code says so and relies on the `last_reported` rule. The threshold stays 600 seconds unless the maintainer prefers three polls.
2. **A write that is not confirmed (WS1).** The brief says a write has failed when the backend is not publishing or `apply_charge_plan` returns not-ok. Today the writer logs "could not confirm" and returns success, so a write that GivTCP dropped is never retried. If Real Time Control is off, retries would be dropped too, so retrying wastes nothing on the inverter, but it is not free (the write count is a lifetime budget). Proposal: an unconfirmed write counts as failed for the retry schedule, the schedule is the brief's (+2, +5, +10, +20 minutes), and the existing repair stays. This needs the maintainer's yes because it changes what the writer returns.
3. **Where the solar shape lives (FS2).** The brief says `core/solar_day.py` is the likely home. That file settles whether the solar day has started (a dawn and dusk debounce). It has nothing to do with the curve. Proposal: a new `core/solar_shape.py` holds `solar_shape_from_periods`.
4. **Pre-release tags.** `.github/workflows/prerelease.yml` matches only `v0.18.0b*` and `v0.18.0rc*`, and `CLAUDE.md` says to change them for the next line. RN2 must change them to `v0.19.0b*` and `v0.19.0rc*`, with the workflow tests updated in the same pull request. The brief does not say so.
5. **Changelog headings (RN1).** The brief asks for Added, Changed and Removed. The repo groups by theme with one Upgrading list (see v0.18.0 and v0.18.1). Proposal: keep the repo's convention and put the three attribute removals first under Upgrading.
6. **One card to one pull request.** The brief makes about 45 cards, so about 45 pull requests. For 0.18 the maintainer asked for fewer, larger pull requests in one stack with no limit on how many are open. Proposal: the same here, grouped as in section 4. Behaviour cards that move golden files stay separate from refactor cards that must move none.
7. **Which counts are right.** The brief quotes about 88 mentions of "givtcp" in `coordinator.py` and similar counts for other files. Those were true at v0.18.0 and will be searched again at IB4, as the brief says.
8. **Dry-run check location (Appendix C, question 2).** Default: the coordinator keeps the check before every call, as the brief proposes, and a unit test pins that nothing reaches the backend in dry run. The adapter does not take a port.
9. **Rules and skills (section 15).** The table is a search result, not an audit. RU4 is the audit. Additions found now: `safety.md` must describe the unconfirmed-write repair and the frozen-feed repair (both raised by code, neither by the write audit, so the "audit never raises a repair" sentence stays true), and the prerelease patterns in item 4.

## 4. How the work is grouped

Order follows Part A section 11. "Moves goldens" lists the golden files that change on purpose.

| # | Pull request | Cards | Moves goldens | Blocked by |
|---|---|---|---|---|
| 1 | Design documents and roadmap (this one) | SP0, RM1, HK2 | none | nothing |
| 2 | The interface and the moved discovery and writer | IB1 to IB3, RU1 | none | nothing |
| 3 | The moved sequences and reads, with staleness | IB4, IB5, RU2 | none | PR 2 |
| 4 | Neutral names, remove the rate comparison, contract tests | IB6, IB7, RA1 | engine snapshots (the removed field only) | PR 3 |
| 5 | Rate defaults on the setup page | RA2, RA3 | config flow forms | PR 4 |
| 6 | The competing-controller warning | CC1 to CC3 | dashboard matrix, entity snapshot | PR 3 |
| 7 | Retry a missed write and show it | WS1, WS3 | none | PR 3, section 3 item 2 |
| 8 | Seasonal rules as settings | SR1 to SR3 | config flow forms | PR 3 |
| 9 | Survive a GivTCP upgrade: the counter guard | SY4 (part) | none | PR 3 |
| 10 | Compare the simulation with SPEC-001 | SP1 | none | PR 3 |
| 11 | Re-plan inside the cheap window | WS2 | none | PR 7, U2 |
| 12 | The forecast shape | FS1 to FS3 | engine snapshots only for cases that use a shape | U3 (provider data) |
| 13 | System types: discovery, selection, docs | SY0 to SY3, rest of SY4 | config flow forms | U5 (entity lists) |
| 14 | The GivEnergy EV charger | GE0 to GE3 | forms, entity snapshot | U4 (entity list, for exact strings) |
| 15 | Housekeeping, audit, release | HK1, HK3, HK4, RU4, RN1, RN2 | none | everything |

Pull requests 2 to 10 can start at once. Pull request 6 does not depend on 4 or 5. Pull requests 12 to 14 start when their evidence arrives, and each starts with a spike note in `docs/design/spikes/`.

## 5. What is blocked

| Card | What is missing | Who supplies it |
|---|---|---|
| WS2 | Whether GivTCP applies a changed charge target inside an open window (U2) | The maintainer, on the test instance |
| FS1 to FS3 | Real Solcast and Forecast.Solar states and attributes for tomorrow (U3) | The maintainer |
| SY0 to SY3 | Anonymised entity lists for the configurations marked "fixture needed" (U5, Appendix D.6) | The maintainer and owners of those systems |
| GE0 to GE3 | An entity list from a GivEnergy EV charger, for exact state strings (U4). GE1 to GE3 can start on the documented names with fakes labelled as such | The maintainer |
| HK3 | The browser checks from the 0.18 spikes | The maintainer |
| SR2 | A yes or no on the proposed winter behaviour | The maintainer |
| GE2 | A yes or no on mapping "use surplus only" to the charger's Solar mode | The maintainer |
| RN2 | A rehearsal on the test instance and one dry-run night | The maintainer |

## 6. What the maintainer is asked for

One list, merged from Part A section 12 and Appendix C. Items with a default proceed on the default unless the maintainer says otherwise.

1. **Retry an unconfirmed write?** (section 3, item 2). Default: yes, on the brief's schedule.
2. **Staleness limit.** Default: 600 seconds, plus `Data_Age` and `status` where they exist.
3. **Re-planning default.** Default: off behind a control until U2 is confirmed, then on without a control. The control is a switch in `controls.py`.
4. **Winter with forecast.** Default: the normal plan with the shoulder floor, and off unless the user turns it on.
5. **GivEnergy charger.** Default: Solar for "use surplus only", never Grid, never Charge Control to stop, never Plug and Go off, never Hybrid automatically.
6. **GivTCP's default rates.** Default: skip 0.395, 0.155 and 0.04 exactly, and pre-fill nothing when all three match.
7. **Minimum GivTCP version.** Default: the wizard warns below 3.6.2. 3.6 and 3.6.1 reset entity ids and mis-handle slot 2 and PV-only inverters. 3.5 keeps working where the fixtures show it does.
8. **Package layout.** Default: the layout in Part A section 5.2.
9. **Fixtures**, highest priority first (Appendix D.6): parallel All-In-Ones with a gateway at two GivTCP versions; an All-In-One with and without a gateway; three-phase; an HV Gen 3 hybrid before and after 3.6; a hybrid with several batteries; AC-coupled; two inverters; a custom prefix. Each as an anonymised entity list with the GivTCP version.
10. **The charge target test (U8).** One system is already evidence (section 7). The first night on GivTCP 3.6.3 checks it again. A real charge on a second per-slot-target inverter, or an All-In-One, would settle it. If `Target_SOC` does not stop the charge there, the write sequence needs its own card.
11. **Entity checks on a live GivTCP (M10).** Done for one hybrid (section 7). Repeat on any other system type that is supplied as a fixture.

## 7. Evidence already collected from one live install

Read-only, on 12 October 2026, from one single-phase hybrid on GivTCP 3.6.3. It answers some of the questions above for that system only. It is not a fixture and no other system type is covered.

| Question | Finding | Effect on the plan |
|---|---|---|
| `Data_Age` exists (item 2, U10) | Yes: `sensor.givtcp_<serial>_data_age`, a number of seconds (read as 1.2), updated on each poll | `is_publishing()` can read it where present. The check still needs the `last_reported` rule for GivTCP 3.5 |
| `Invertor_Type` (U10) | `sensor.givtcp_<serial>_invertor_type` reads `Hybrid_gen3`. The exact string is `Hybrid_gen3`, with an underscore and a lower-case generation | SY1 classification can match this string for this kind. Other kinds still need fixtures |
| `GivTCP_Version` | `sensor.givtcp_<serial>_givtcp_version` reads `3.6.3` | Version is readable. 3.6.3 exists, so the supported floor in item 7 is a floor and not a pin |
| SmartTarget or PALM entity (U1, CC1) | No entity has "smart" or "palm" in its name | CC1 is answered: no entity. CC2 stays behaviour based |
| Per-slot targets (U8) | `Charge_Target_SOC_1` to `_10` exist as numbers, all reading 100 and never changed in the last seven days. Over the same days the manager wrote `Target_SOC` (86, 88, 90) with `Enable_Charge_Target` on, and the battery stopped at about the written target on the nights it had time to reach it | On this inverter `Target_SOC` with `Enable_Charge_Target` stops the charge while slot 1's own target reads 100. That was on GivTCP 3.5. The first night on 3.6.3 repeats the test. U8 is partly answered for one system, and a real charge on another per-slot inverter is still wanted |
| Battery capacity (C29) | `Battery_Capacity_kWh` exists (19.046). No `Battery_Capacity_kWh_calc` entity was found | C29 reads `Battery_Capacity_kWh`. The `_calc` variant is not on this system |
| Publish behaviour | The SoC sensor did not move `last_reported` for over an hour while its value stayed the same, so GivTCP publishes it only on a change. Grid and load power change nearly every poll | The frozen-feed rule needs several sensors quiet, as built. Prefer `Data_Age` |

Still to collect without anyone's help: a link check of every URL in the roadmap text (card RM1). Each failure is listed in the pull request that adds the text.

## 8. Risks added by the plan

| Risk | Effect | What to do |
|---|---|---|
| The frozen-feed rule depends on GivTCP republishing, and it publishes some sensors only on a change (the SoC sensor did not move `last_reported` for over an hour on one install) | A night with every one of solar, battery power, grid and load perfectly steady for 10 minutes would read as frozen | The rule needs all five quiet, and it clears at once. Prefer `Data_Age` where it exists. Keep the false-positive case in the contract tests |
| Retrying an unconfirmed write spends register writes | The write count is a lifetime budget | The brief's caps stay (four retries, 15 minutes before the end), and the count is shown in the log |
| The brief's Appendix D rests on GivTCP 3.6 documentation read in October 2026 | Entity names and states are unproved until fixtures arrive | No discovery or mapping code without a fixture, as the brief says |

The brief's own risk table (Part A section 14) still applies.
