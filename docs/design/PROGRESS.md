# Progress

One line per card. A card is listed as merged only when its pull request is merged into `main`. Update this file in the pull request that merges the card.

## Progress on 0.19.0

The cards are grouped into pull requests in [RELEASE_0.19_PLAN.md](RELEASE_0.19_PLAN.md), section 4. "Blocked" says what is missing, from section 5 of the plan.

| Card | What | State |
|---|---|---|
| IB1 | Define the interface and the pure types | Not started |
| IB2 | Move discovery into the adapter | Not started |
| IB3 | Move the writer | Not started |
| IB4 | Move the write sequences out of the coordinator | Not started |
| IB5 | Move reading and availability | Not started |
| IB6 | Neutral names in `core/` and in comments | Not started |
| IB7 | Contract tests and a second fake | Not started |
| RA1 | Remove the GivTCP rate comparison | Not started |
| RA2 | Rate defaults on the setup tariff page | Not started |
| RA3 | Changelog and docs for the rates change | Not started |
| WS1 | Retry a missed daily write | Not started. Needs a yes from the maintainer on counting an unconfirmed write as failed (plan, section 3 item 2) |
| WS2 | Re-plan inside the cheap window | Blocked: whether GivTCP applies a changed charge target inside an open window (U2) |
| WS3 | Make retries and re-plans visible | Not started |
| CC1 | Spike: can we read whether SmartTarget is on? | Not started |
| CC2 | Detect another controller | Not started |
| CC3 | The sensor, the banner and the docs | Not started |
| FS1 | Spike: what do the forecast providers give us? | Blocked: real Solcast and Forecast.Solar states and attributes for tomorrow (U3) |
| FS2 | Use the shape in the simulation | Blocked: the FS1 provider data (U3) |
| FS3 | Say which shape was used | Blocked: the FS1 provider data (U3) |
| SR1 | Seasonal rules as configuration | Not started |
| SR2 | Use the settings in the engine | Blocked: a yes or no on the proposed winter behaviour |
| SR3 | Docs | Not started |
| SY0 | Fixtures | Blocked: anonymised entity lists for the configurations marked "fixture needed" (U5, Appendix D.6) |
| SY1 | Discovery that does not assume one inverter or one prefix | Blocked: the SY0 fixtures (U5) |
| SY2 | Selection rules and the wizard | Blocked: the SY0 fixtures (U5) |
| SY3 | Docs and honesty | Blocked: the SY0 fixtures (U5) |
| SY4 | Survive a GivTCP upgrade | Not started. Part can start after IB5 |
| GE0 | Fixtures for the GivEnergy EV charger | Blocked: an entity list from a GivEnergy EV charger (U4) |
| GE1 | Discover and read the charger | Not started. Can start on the documented names, with fakes labelled as such |
| GE2 | Set the charger's mode | Blocked: a yes or no on mapping "use surplus only" to the charger's Solar mode |
| GE3 | Docs and messages | Not started. Can start on the documented names |
| HK1 | README accuracy | Not started |
| HK2 | Progress notes | In the roadmap PR (`r019/roadmap`) |
| HK3 | Outstanding browser checks | Blocked: the browser checks from the 0.18 spikes, run by the maintainer (U7) |
| HK4 | Requirements and quality scale | Not started |
| SP0 | The specification method | In the design docs PR |
| SP1 | Check the charge simulation against SPEC-001 | Not started. After IB1 to IB5 |
| SP2 | Write and review the specifications | Not started. A series, not blocking |
| RM1 | Roadmap: the competitor review | In the roadmap PR (`r019/roadmap`) |
| RN1 | Changelog | Not started |
| RN2 | Release | Blocked: a rehearsal on the test instance and one dry-run night, run by the maintainer |
| RU1 | `CLAUDE.md` | Not started |
| RU2 | `safety.md` | Not started |
| RU3 | The other rule files and the skills | Not started |
| RU4 | Audit | Not started |

## Progress on 0.18.0

All 0.18 cards are merged. Release v0.18.0 was published on 11 October 2026 and v0.18.1 on 12 October 2026. Cards DB3 and DB4 were not built, by the SP1 decision.

0.18.1 added the repair for charge writes the inverter does not take and the frozen-feed check.

| Card | What | State |
|---|---|---|
| SP1 | Persistent dashboard through the dashboards collection | Merged. Result partly, no clean route: see [SP1](spikes/SP1.md) |
| SP2 | Server-side admin check, frontend items | Merged. Admin check yes, frontend items need a browser: see [SP2](spikes/SP2.md) |
| SP3 | Checklist wizard pattern and `async_update_and_abort` | Merged. Yes, no menu fallback needed: see [SP3](spikes/SP3.md) |
| FN3 | Mock GivTCP and the write-sequence test | Merged. In-process, no MQTT broker: see [mock_givtcp](mock_givtcp.md) |
| CT1 | Dry run switch and the test instance marker file | Merged. The marker forces dry run in the coordinator, the snapshot, the sensor, the log and the diagnostics |
| CT2 | Immersion divert thresholds as numbers | Merged. Created only while an immersion switch is set |
| CT3 | Verbose logging, cheap rate floor, skip-charge threshold and forecast conservatism | Merged. The wizard and Configure page fields are gone |
| CT4 | Translations and icons for every switch and number | Merged. `entity-translations` and `icon-translations` are done |
| WZ1 | Page logic as pure functions over a page table | Merged. `core/wizard_model.py`, `wizard_tariff.py`, `wizard_pages.py` and `wizard_changes.py`, used by both wizards. No storage change |
| WZ2 | One home per setting | Merged. `forecast_provider`, the charger chooser and the immersion temperature and car efficiency questions at setup are gone. The key `forecast_provider` stays in the reload table because an old entry may hold it |
| WZ3 | Options read at save time | Merged. The confirm step returns the current options with only the changed keys replaced |
| WZ4 | Setup wizard | Merged. Checklist, routing to the ticked pages in a fixed order, `last_step`, nothing stored before confirm. Three screens for a flat-rate home |
| WZ5 | Options wizard | Merged. "What would you like to change?", a rows screen with as many rows as the count, a confirm step with before and after, skipped for one live page |
| WZ6 | Reconfigure as the inverter connection | Merged. `async_update_and_abort`, one reload, a serial check that ignores case. The tariff reconfigure moved to the Tariff page of the options wizard |
| WZ7 | Detect first | Merged. A Solcast or Forecast.Solar sensor, an EV charger and the Home Assistant currency are used without a page. Immersion switch candidates are listed, never applied |
| WZ8 | Translations | Merged. `strings.json` and `translations/en.json` are restructured and stay byte identical. `strings.json` is not deleted, see below |
| WZ9 | Thin `config_flow.py` | Merged. 42 lines. The steps are in `wizard/` |
| WZ10 | Config diet review | Merged: [CONFIG_DIET](CONFIG_DIET.md) |
| DB1 | Strategy listed under Community dashboards | Merged. Registered in `window.customStrategies` with create suggestions. The frontend side is unverified, see the manual checks in [SP2](spikes/SP2.md) |
| DB2 | Server-side admin check | Merged. `connection.user.is_admin` decides the Settings view. The view keeps a `visible` list for Take control |
| DB3 | Create the dashboard once | Not built, by the SP1 decision. Setup finds an existing dashboard or sends one notification, and saves the answer in `dashboard_url_path` |
| DB4 | Remove an unedited dashboard with the entry | Not built. The integration creates no dashboard, so it deletes none. Removing the last entry dismisses the notification |
| DB5 | Fallback notification | Merged. It is the main path now. Tested with the lookup failing |
| DB6 | Delete the YAML action, file and button | Merged. The Refresh Dashboard button entity is removed too |
| DB7 | Replace apexcharts-card | Merged. No `apexcharts` string in the builder |
| DB8 | power-flow-card-plus stays optional | Merged. Used only when listed in the Lovelace resources |
| DB9 | Setup checklist and dry run banner | Merged. The banner shows tonight's charge plan, because no sensor holds a general next action |
| DB10 | Node test of the strategy JS | Merged. Runs inside the unit suite, and fails in CI when node is missing |
| DB11 | Real Home Assistant test of the dashboard lifecycle | Merged. Add, reload, delete and remove against a real Lovelace. No CI job change |

## Open questions from 0.18

1. **Dashboard auto-create.** SP1 found no clean route, so the dashboard registers the strategy, lists it under Community dashboards and sends one notification. The maintainer decides whether to accept the borrowed-admin in-process route later (SP1, Decision, point 2).
2. **Frontend checks (SP2).** Take control on a custom strategy, `getCreateSuggestions`, `window.customStrategies` and the distribution card are unverified. The manual checks are in [SP2](spikes/SP2.md).
3. **Take control and the Settings view.** If Take control freezes the generated config, an admin taking control could freeze the admin-only Settings view into a dashboard everyone can open. Keep a `visible` user condition as well as the server decision, unless the manual check shows otherwise.
4. **Floor 2026.5.0.** The spikes ran on Home Assistant 2026.9.4 only. Re-run `tests/ha_e2e/spikes` on the floor once CI has a job for it (FN4).
5. **Xiaomi Home source.** The wizard pattern was tested as the brief describes it. Its source was not read.
6. **MQTT instance.** The mock is in-process. Whether a Mosquitto-based disposable instance is still wanted is the maintainer's call.
7. **Delete `strings.json`.** The plan for the translation card was to delete it, but the repository keeps `strings.json` and `translations/en.json` byte identical and a test checks it. A custom integration reads `translations/en.json` at runtime, so deleting `strings.json` should be safe once hassfest in CI agrees. Left for the maintainer.
8. **Hassfest.** It could not run here (it ships with Home Assistant core, not with the package). The new strings were checked by the end-to-end suite for labels, help text and placeholders, but not by hassfest.
