# Progress

One line per card. A card is listed as merged only when its pull request is merged into `main`. Update this file in the pull request that merges the card.

## Progress on 0.19.0

Tracked in GitHub issues, starting at #304: one child per pull request group, one grandchild per card. A closed issue means the card is merged. The grouping is in [RELEASE_0.19_PLAN.md](RELEASE_0.19_PLAN.md).

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
