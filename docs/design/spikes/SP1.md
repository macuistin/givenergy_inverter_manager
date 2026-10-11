# SP1: creating a persistent dashboard

## Question

Against real Home Assistant 2026.9.4, can the integration create, rename and delete a persistent storage dashboard (one that points at the `custom:givenergy-manager` strategy), and does it survive a restart? If so, through which route, and is that route clean?

"Clean" here means a route that uses a documented or at least public entry point, that does not borrow an identity the integration does not hold, and that keeps working when the next Home Assistant release moves internals.

## Method

`tests/ha_e2e/spikes/test_sp1_dashboard_creation.py` sets up the real `lovelace` component (not a stub) with the harness's storage mock (`hass_storage`) and an empty configuration. The `frontend` component is not set up, because its Python package is not installed in the e2e environment (see SP2). Lovelace registers its panels through `frontend.async_register_built_in_panel`, which works without the component, so the sidebar entry can be inspected as a `Panel` object.

"Restart" means: write out the delayed store saves (as shutdown does), start a second `HomeAssistant` over the same mocked storage, and set `lovelace` up again. The `lovelace` component has no reload or unload, so a restart is the only way to repeat its setup.

```
python -m pytest tests/ha_e2e/spikes/test_sp1_dashboard_creation.py -q
```

## Result: partly

The persistent dashboard can be created, renamed, deleted and it survives a restart. **No route open to integration code is clean.** The only complete route is the admin-only websocket command, and from integration code it is reachable only by borrowing an admin identity.

### What works (route A, the websocket command `lovelace/dashboards/create`)

| Claim | Result | Evidence (test) |
|---|---|---|
| A url path without a hyphen fails unless `allow_single_word: true`; `givenergy` then works and the flag is not stored | yes | `test_a_url_path_without_a_hyphen_needs_allow_single_word` |
| The dashboard becomes a sidebar panel (component `lovelace`, title, icon, `require_admin` false, `show_in_sidebar` true, config `{"mode": "storage"}`) and is listed by `lovelace/dashboards/list` | yes | `test_a_created_dashboard_is_a_visible_sidebar_panel_listed_in_settings` |
| A new dashboard has no config until one is saved (mode `auto-gen`). The strategy pointer is saved with `lovelace/config/save` or from code with `hass.data[LOVELACE_DATA].dashboards[url_path].async_save(...)`, and read back | yes | `test_a_strategy_pointer_can_be_saved_and_read_back` |
| Rename (title, icon) updates the panel and keeps the pointer; the url path cannot be changed | yes | `test_a_rename_updates_the_panel_and_keeps_the_pointer` |
| Delete removes the panel, the collection item and the stored config file (`lovelace.<id>`) | yes | `test_a_delete_removes_the_panel_the_item_and_the_stored_config` |
| Create, pointer and rename survive a restart, and a rename is not reset | yes | `test_a_create_and_pointer_and_rename_survive_a_restart` |
| A dashboard the user deleted stays deleted after a restart (so "never recreate" only needs the integration to not run the create again) | yes | `test_a_dashboard_the_user_deleted_stays_deleted_after_a_restart` |
| Create is admin only (read-only user gets `unauthorized`) | yes | `test_a_create_is_admin_only` |
| A url path another panel already uses is refused (`url_already_exists`), so the "skip and notify" lifecycle row is testable | yes | `test_a_create_refuses_a_url_path_another_panel_already_uses` |
| Integration code can drive the same command in-process with its own `ActiveConnection`, but only with an admin user | yes, with that condition | `test_a_in_process_dispatch_of_the_command_needs_an_admin_identity` |

Naming detail: the item id is the slug of the url path (`givenergy-x` becomes `givenergy_x`), and the config lives in `.storage/lovelace.<id>`. Rename and delete take `dashboard_id`, not the url path.

### Why no route is clean

- **The collection is not reachable.** In `lovelace/__init__.py` the `DashboardsCollection` is a local variable of `async_setup` (line 291). It is not in `hass.data[LOVELACE_DATA]` (`test_b_the_collection_is_not_in_hass_data`). The only creation entry point is the websocket command (registered at line 303, `helpers/collection.py:600` wraps it in `require_admin`).
- **A second `DashboardsCollection` of our own does not work** (route B). It writes to the same store key but has no listener, so no panel and no `LovelaceStorage` is registered and the settings list does not show it (`test_b_our_own_collection_instance_is_invisible_to_the_running_component`). The live collection later saves its own item list over ours, so the dashboard is lost the next time the user adds any dashboard (`test_b_an_item_written_by_our_own_collection_is_overwritten_by_the_live_one`).
- **The live collection can be reached by reflection only**: `hass.data["websocket_api"]["lovelace/dashboards/list"][0].__self__.storage_collection` is the live `DashboardsCollection`, and `async_create_item` on it registers the panel (`test_b_the_live_collection_is_reachable_by_unwrapping_a_registered_handler`). That relies on a private table, a bound-method layout and a private attribute.
- **The ephemeral route** (route C: register a `LovelaceStorage` in `hass.data[LOVELACE_DATA].dashboards` and a panel with `frontend.async_register_built_in_panel`) renders and is listed in Settings, but the collection does not know it. Rename and delete from the UI fail with `not_found`, it is not in `lovelace_dashboards`, it disappears at restart and leaves an orphaned `lovelace.givenergy` file (`test_c_the_ephemeral_route_renders_but_the_ui_cannot_manage_it`, `test_c_the_ephemeral_route_is_gone_after_a_restart_and_leaves_an_orphan_file`). The brief already ruled this route out.
- **The in-process websocket dispatch** (route A from code) has three weaknesses. It needs an admin `User` (for example `hass.auth.async_get_owner()`, which is `None` before onboarding), so the integration would act with an identity that did not ask for it, which is exactly what `require_admin` is there to prevent. It depends on the `ActiveConnection` constructor (six arguments in 2026.9.4, including `remote`, `websocket_api/connection.py:66`) and on a `WebSocketAdapter` logger from `websocket_api/http.py:60`, none of which is documented API. And a failure shows up only as a command error reply, not an exception.
- **YAML dashboards** (`lovelace: dashboards:` in `configuration.yaml`, `lovelace/__init__.py:204`) need the user to edit their configuration, so they are not an option.
- **Precedent in core**: core itself creates its Map dashboard with `dashboards_collection.async_create_item(...)` and then saves its strategy config with `hass.data[LOVELACE_DATA].dashboards["map"].async_save(...)` (`lovelace/__init__.py:415` to 430). That is core code holding the collection, not a route offered to integrations.

## Decision

1. **Do not auto-create the dashboard in 0.18.0.** Use the fallback the brief names: the strategy registered under Community dashboards (frontend registration, DB cards) plus a persistent notification with the two-click path. The "Won't have for now" row in `ROADMAP.md` ("An integration-owned dashboard that rewrites the user's Lovelace ... relies on internal Home Assistant APIs") stays as it is. This follows the corrections file: the collection cannot be reached cleanly.
2. **If the maintainer still wants auto-create later**, the least bad route is the in-process dispatch of `lovelace/dashboards/create` with the owner as the connection user, guarded to fail closed (any exception means send the notification), run once at first setup, with `allow_single_word: true` and the pointer saved through `LovelaceStorage.async_save`. The tests in this spike would then move into the permanent e2e suite so that the "latest" and "beta" CI jobs flag a Home Assistant release that breaks it. This is a maintainer decision about accepting borrowed admin identity and private internals. This PR does not implement it.
3. Evidence for the lifecycle rows of the brief, should the route be used: pointer-only config, rename respected, deleted stays deleted, a taken url path is refused, and removal on entry removal can be done with the same command (`lovelace/dashboards/delete`) after reading the stored config to check that it still equals the pointer.

## Not verified

- **Floor 2026.5.0 and the latest release.** Only 2026.9.4 is installed in the e2e environment. Line numbers above are for 2026.9.4.
- **A browser.** That the panel appears in the sidebar and in Settings → Dashboards is checked as a `Panel` object and a websocket list reply. Maintainer check on a test instance: Settings → Dashboards after the dashboard exists.
- **Community dashboards entry** (the fallback) needs the frontend's custom strategy registration; see SP2.
- **A real restart.** The second `HomeAssistant` shares only the mocked storage, not a process restart.
