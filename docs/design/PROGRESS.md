# Progress on 0.18.0

One line per card. A card is listed as merged only when its pull request is merged into `main`. Update this file in the pull request that merges the card.

## Cards

| Card | What | State |
|---|---|---|
| SP1 | Persistent dashboard through the dashboards collection | In the spikes PR (`r018/spikes`). Result partly, no clean route: see [SP1](spikes/SP1.md) |
| SP2 | Server-side admin check, frontend items | In the spikes PR. Admin check yes, frontend items need a browser: see [SP2](spikes/SP2.md) |
| SP3 | Checklist wizard pattern and `async_update_and_abort` | In the spikes PR. Yes, no menu fallback needed: see [SP3](spikes/SP3.md) |
| FN3 | Mock GivTCP and the write-sequence test | In the spikes PR. In-process, no MQTT broker: see [mock_givtcp](mock_givtcp.md) |
| CT1 | Dry run switch and the test instance marker file | In the controls PR (`r018/controls`). The marker forces dry run in the coordinator, the snapshot, the sensor, the log and the diagnostics |
| CT2 | Immersion divert thresholds as numbers | In the controls PR. Created only while an immersion switch is set |
| CT3 | Verbose logging, cheap rate floor, skip-charge threshold and forecast conservatism | In the controls PR. The wizard and Configure page fields are gone |
| CT4 | Translations and icons for every switch and number | In the controls PR. `entity-translations` and `icon-translations` are done |
| DB1 | Strategy listed under Community dashboards | In the dashboard PR (`r018/dashboard`). Registered in `window.customStrategies` with create suggestions. The frontend side is unverified, see the manual checks in the PR |
| DB2 | Server-side admin check | In the dashboard PR. `connection.user.is_admin` decides the Settings view. The view keeps a `visible` list for Take control |
| DB3 | Create the dashboard once | Not built, by the SP1 decision. Setup finds an existing dashboard or sends one notification, and saves the answer in `dashboard_url_path` |
| DB4 | Remove an unedited dashboard with the entry | Not built. The integration creates no dashboard, so it deletes none. Removing the last entry dismisses the notification |
| DB5 | Fallback notification | In the dashboard PR. It is the main path now. Tested with the lookup failing |
| DB6 | Delete the YAML action, file and button | In the dashboard PR. The Refresh Dashboard button entity is removed too |
| DB7 | Replace apexcharts-card | In the dashboard PR. No `apexcharts` string in the builder |
| DB8 | power-flow-card-plus stays optional | In the dashboard PR. Used only when listed in the Lovelace resources |
| DB9 | Setup checklist and dry run banner | In the dashboard PR. The banner shows tonight's charge plan, because no sensor holds a general next action |
| DB10 | Node test of the strategy JS | In the dashboard PR. Runs inside the unit suite, and fails in CI when node is missing |
| DB11 | Real Home Assistant test of the dashboard lifecycle | In the dashboard PR. Add, reload, delete and remove against a real Lovelace. No CI job change |

Merged cards: none yet.

## Open questions

1. **Dashboard auto-create.** SP1 found no clean route, so the dashboard PR registers the strategy, lists it under Community dashboards and sends one notification. The maintainer decides whether to accept the borrowed-admin in-process route later (SP1, Decision, point 2).
2. **Frontend checks (SP2).** Take control on a custom strategy, `getCreateSuggestions`, `window.customStrategies` and the distribution card are unverified. The manual checks are in [SP2](spikes/SP2.md).
3. **Take control and the Settings view.** If Take control freezes the generated config, an admin taking control could freeze the admin-only Settings view into a dashboard everyone can open. Keep a `visible` user condition as well as the server decision, unless the manual check shows otherwise.
4. **Floor 2026.5.0.** The spikes ran on Home Assistant 2026.9.4 only. Re-run `tests/ha_e2e/spikes` on the floor once CI has a job for it (FN4).
5. **Xiaomi Home source.** The wizard pattern was tested as the brief describes it. Its source was not read.
6. **MQTT instance.** The mock is in-process. Whether a Mosquitto-based disposable instance is still wanted is the maintainer's call.
