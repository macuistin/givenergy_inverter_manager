# Progress on 0.18.0

One line per card. A card is listed as merged only when its pull request is merged into `main`. Update this file in the pull request that merges the card.

## Cards

| Card | What | State |
|---|---|---|
| SP1 | Persistent dashboard through the dashboards collection | In the spikes PR (`r018/spikes`). Result partly, no clean route: see [SP1](spikes/SP1.md) |
| SP2 | Server-side admin check, frontend items | In the spikes PR. Admin check yes, frontend items need a browser: see [SP2](spikes/SP2.md) |
| SP3 | Checklist wizard pattern and `async_update_and_abort` | In the spikes PR. Yes, no menu fallback needed: see [SP3](spikes/SP3.md) |
| FN3 | Mock GivTCP and the write-sequence test | In the spikes PR. In-process, no MQTT broker: see [mock_givtcp](mock_givtcp.md) |
| CT1 | The test instance marker file | In the controls PR (`r018/controls`). The marker forces dry run in the coordinator, the snapshot, the sensor, the log and the diagnostics |

Merged cards: none yet.

## Open questions

1. **Dashboard auto-create.** SP1 found no clean route, so the proposal is the registered strategy, the Community dashboards entry and a notification. The maintainer decides whether to accept the borrowed-admin in-process route later (SP1, Decision, point 2).
2. **Frontend checks (SP2).** Take control on a custom strategy, `getCreateSuggestions`, `window.customStrategies` and the distribution card are unverified. The manual checks are in [SP2](spikes/SP2.md).
3. **Take control and the Settings view.** If Take control freezes the generated config, an admin taking control could freeze the admin-only Settings view into a dashboard everyone can open. Keep a `visible` user condition as well as the server decision, unless the manual check shows otherwise.
4. **Floor 2026.5.0.** The spikes ran on Home Assistant 2026.9.4 only. Re-run `tests/ha_e2e/spikes` on the floor once CI has a job for it (FN4).
5. **Xiaomi Home source.** The wizard pattern was tested as the brief describes it. Its source was not read.
6. **MQTT instance.** The mock is in-process. Whether a Mosquitto-based disposable instance is still wanted is the maintainer's call.
