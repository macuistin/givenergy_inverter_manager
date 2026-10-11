# SP3: the wizard pattern

## Question

Do these work in a real Home Assistant, in a setup flow and in an options flow?

1. A checklist step (multi-select of page ids) with dynamic routing to later steps.
2. `last_step=False` on every form but the last, `last_step=True` on the confirm step.
3. Nothing stored until the confirm step, then one write that merges into the current options.
4. `async_update_and_abort` with an update listener gives one reload, and what the 2026.12 deprecation logs.
5. The same pattern as Xiaomi Home's integration (checkboxes gate the next steps, a confirm step summarises, one write at the end).

## Method

`tests/ha_e2e/spikes/sp3_support.py` defines a throwaway handler and its fixtures, and three modules use it: `test_sp3_config_flow.py` (setup flow), `test_sp3_options_flow.py` (options flow) and `test_sp3_reload.py` (`async_update_and_abort` and the deprecation). The handler is registered (domain `sp3_wizard`) with `mock_integration` and `mock_config_flow`. It is removed after each test and nothing under `custom_components/` is used. The integration registers an update listener that calls `async_schedule_reload`, as `givenergy_inverter_manager` does. Flows are driven through the real flow managers, and one test goes through the REST view the frontend uses (`/api/config/config_entries/flow`).

Run with real Home Assistant 2026.9.4 (the version `requirements-test-e2e.txt` pins):

```
python -m pytest tests/ha_e2e/spikes/test_sp3_config_flow.py tests/ha_e2e/spikes/test_sp3_options_flow.py tests/ha_e2e/spikes/test_sp3_reload.py -q
```

## Result: yes

| Claim | Result | Evidence (test) |
|---|---|---|
| Checklist step routes only to ticked pages, in a fixed order whatever order the client sends | yes | `test_config_flow_checklist_routes_only_to_ticked_pages` |
| Nothing ticked goes straight to the confirm step | yes | `test_config_flow_with_nothing_ticked_goes_straight_to_confirm` |
| An answer on one form decides how many rows the next form has (the schema is built when the form is shown) | yes | `test_config_flow_answer_decides_how_many_rate_rows_the_next_form_has` |
| `last_step` is False on every page form and True on the confirm form | yes | the same tests assert `flow["last_step"]` at each screen |
| "Step n of about m" can change per screen through `description_placeholders` | yes | `test_config_flow_step_counts_are_recomputed_per_screen` |
| The checklist serialises for the frontend API: `last_step`, a `select` selector with `multiple: true`, `mode: list` | yes | `test_checklist_form_serialises_for_the_frontend_api` |
| Setup flow stores nothing until confirm: no entry, nothing in `core.config_entries`, no setup, and an abort at the confirm step leaves nothing | yes | `test_config_flow_stores_nothing_until_confirm` |
| Options flow makes exactly one `async_update_entry` call, after confirm | yes | `test_options_flow_routes_and_writes_once_at_confirm` |
| Reading `self.config_entry.options` at confirm keeps a live key changed while the wizard was open | yes | `test_options_confirm_merges_the_current_options_not_a_copy_from_flow_start` |
| Copying the options in `__init__` (the v0.17.1 pattern) loses that live change | yes, it is a real hazard | `test_control_a_flow_that_copies_options_at_creation_overwrites_a_live_change` |
| Nothing ticked in the options wizard can abort without a write | yes | `test_options_flow_nothing_ticked_aborts_without_a_write` |
| A confirm with unchanged values does not notify the listener, so no reload | yes | `test_options_confirm_without_changes_does_not_notify_the_listener` |
| `async_update_and_abort` plus a listener reloads once and logs nothing | yes | `test_update_and_abort_with_a_listener_reloads_once_and_logs_nothing` |
| `async_update_and_abort` without a listener does not reload | yes | `test_update_and_abort_without_a_listener_does_not_reload` |
| `async_update_and_abort` with unchanged data does not notify the listener | yes | `test_update_and_abort_with_unchanged_data_does_not_notify_the_listener` |

Mutation spot-check, done once: making the routing ignore the ticks failed 8 tests, and making the confirm step ignore the current options failed 2.

## What Home Assistant does, with source references

All paths are in the installed `homeassistant` 2026.9.4 package.

- **Forms and menus.** `data_entry_flow.py:706` `async_show_form(... last_step ...)` passes `last_step` straight into the result (line 724), and the flow manager keeps whatever `step_id` the form names. `async_show_menu` is at line 878 (the fallback if it were needed).
- **Options flow finish writes what you return.** `config_entries.py:3935` (`OptionsFlowManager.async_finish_flow`) calls `async_update_entry(entry, options=result["data"])`. It replaces the options with the data the flow returns, so the confirm step must return the merged dict (current options plus the changed keys), not just the changes.
- **A listener is notified only when something changed.** `config_entries.py:2545` `async_update_entry` returns False when nothing changed (line 2668) and `_async_save_and_notify` (line 2674) runs the listeners otherwise.
- **`async_update_and_abort`** is at `config_entries.py:3505`. It updates and aborts and does not reload and does not report anything.
- **`async_update_reload_and_abort`** is at `config_entries.py:3547`. With an entry that has update listeners it calls `report_usage("has an update listener and should use it for scheduling a reload", ..., breaks_in_ha_version="2026.12.0")` (lines 3586 to 3592) and then schedules a reload itself.
- **`_abort_if_unique_id_configured(updates=..., reload_on_update=True)`** has the same report at `config_entries.py:3174` to 3179. The integration calls it without `updates` (config_flow.py lines 551 and 580), so this does not apply today.
- **`OptionsFlowWithReload`** (`config_entries.py:4061`) raises `ValueError("Config entry update listeners should not be used with OptionsFlowWithReload")` when the entry has update listeners (line 3961). It cannot be used while the entry keeps its listener.
- **`async_schedule_reload`** (`config_entries.py:2464`) creates a task each call. It does not coalesce.
- **The deprecation is logged once per integration and message per Home Assistant run.** `helpers/frame.py:298` to 301 keeps a `_REPORTED_INTEGRATIONS` set keyed by `domain:what`.

## What the 2026.12 deprecation logs

Measured with the update listener registered and `async_update_reload_and_abort` called (`test_update_reload_and_abort_with_a_listener_logs_the_2026_12_deprecation`):

```
WARNING Detected that custom integration 'sp3_wizard' has an update listener and should use it for
scheduling a reload. This will stop working in Home Assistant 2026.12.0, please <report issue text>
```

It is at WARNING level and is logged once per run (`test_the_deprecation_is_logged_once_per_run_for_an_integration`). The same call also caused **two reloads for one change** (the listener's reload and the helper's own), so the helper is wrong for this integration even before 2026.12.

## Decision

The wizard goes ahead as designed. **No menu-based fallback is needed** for the flow mechanics: routing, `last_step`, confirm placeholders and the single write all work in both a setup flow and an options flow. Rules that follow from the evidence, for the wizard cards:

1. Read `self.config_entry.options` at confirm time and return `{**current, **changed_keys}` from `async_create_entry`. Never copy options in `__init__`.
2. Reconfigure uses `async_update_and_abort`; the existing update listener decides the reload. Do not call `async_update_reload_and_abort`, do not pass `updates` with `reload_on_update` to `_abort_if_unique_id_configured`, and do not subclass `OptionsFlowWithReload`.
3. A confirm with no change does nothing (no reload), so the wizard needs no extra guard for that.

## Not verified

- **The 2026.5.0 floor.** Only 2026.9.4 is installed in the e2e environment. The `async_update_and_abort` and `async_update_reload_and_abort` signatures and the report text are from 2026.9.4. Run this file with the floor's pinned plugin release once the CI matrix (FN4) has one.
- **How the frontend draws any of it.** The test proves the serialised schema and `last_step`. That the multi-select renders as a list of checkboxes and that `last_step=False` labels the button "Next" needs a browser. Maintainer check: start the setup flow on a test instance and look at the first screen.
- **The Xiaomi Home source.** The brief says the pattern was checked there; this spike did not read it. The test builds the pattern the brief describes (checklist, routing, confirm summary, one write) and shows it works. A checkbox-per-page encoding (one boolean per page) would route the same way and is not tested separately.
