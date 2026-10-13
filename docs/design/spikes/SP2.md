# SP2: server-side admin check, and what only a browser can show

## Question

1. Does a custom websocket handler see `connection.user.is_admin`, for an administrator and for a non-administrator, with extra client fields ignored?
2. What is the handler pattern of the existing strategy command, and what changes for a server-side admin decision?
3. Do Take control on a custom strategy, `getCreateSuggestions`, `window.customStrategies` and the distribution card work with this integration?

## Method

`tests/ha_e2e/spikes/test_sp2_websocket_admin.py`, against real Home Assistant 2026.9.4 with real websocket clients (`hass_ws_client`) for an admin user and a read-only user. The handler under test is a throwaway handler written in the same decorator shape as `strategy.py`. Two tests also run the real `givenergy_inverter_manager/dashboard` command through a loaded entry.

```
python -m pytest tests/ha_e2e/spikes/test_sp2_websocket_admin.py -q
```

## Result

| Question | Result |
|---|---|
| 1. `connection.user.is_admin` in a custom handler | **yes** |
| 2. Handler pattern and the change needed | **yes**, see below |
| 3. Take control, `getCreateSuggestions`, `window.customStrategies`, distribution card | **cannot verify offline**: the frontend package is not installed. Manual checks below |

### Question 1, evidence

| Claim | Evidence (test) |
|---|---|
| The handler reads `connection.user.is_admin`: true for an admin client, false for a read-only client | `test_handler_reads_is_admin_for_an_admin_and_for_a_read_only_user` |
| The existing schema (`{Required("type"): ...}`) rejects extra client fields with `invalid_format`, so a client cannot send an `admin` flag at all | `test_the_existing_schema_rejects_extra_client_fields`, and on the real command `test_the_real_command_rejects_extra_client_fields` |
| A schema that allows extras still ignores a claimed `is_admin` or `admin`: the read-only client's own role is returned | `test_a_schema_that_allows_extras_ignores_a_claimed_admin_flag` |
| A role change shows on the next message of an open connection, with no reconnect | `test_a_role_change_shows_on_the_next_message_of_an_open_connection` |
| `is_admin` is false for a deactivated administrator | `test_a_deactivated_administrator_is_not_an_admin` |

Source: `ActiveConnection.user` is set in `websocket_api/connection.py:79` from the refresh token's user (`websocket_api/auth.py:111`), and `User.is_admin` (`auth/models.py:90`) is `is_owner` or (`is_active` and a member of the admin group).

### Question 2, the handler pattern and the gap

`strategy.py` registers one command, `givenergy_inverter_manager/dashboard`, inside `_register_websocket_command`:

- `@websocket_api.websocket_command({vol.Required("type"): WS_TYPE})` then `@websocket_api.async_response`, signature `(hass, connection, msg)`, registered with `websocket_api.async_register_command(hass, ws_dashboard)`;
- registered once per Home Assistant run (guarded by `hass.data[_REGISTERED_KEY]`) and left in place on unload, so with no loaded entry it answers `not_found`;
- it builds the dashboard for the first loaded entry and never looks at `connection.user`.

Today the admin decision is made in the payload: `async_admin_user_ids` lists the administrators and the Settings view carries `visible: [{"user": <id>}]`. **The server still sends the whole Settings view to every client**: `test_the_real_command_today_sends_the_settings_view_to_a_read_only_user` shows a read-only user's response includes the `settings` view with its cards, hidden only by the frontend honouring `visible`. The server-side decision (brief section 8) closes this by reading `connection.user.is_admin` in `ws_dashboard` and leaving the Settings view out of the payload for everyone else. The pattern above needs only that one line in the handler and a boolean passed to `async_dashboard_for_websocket` and `build_dashboard`, replacing the administrator ID list. Because the existing schema already rejects unknown keys, no extra validation is needed.

**Design risk to settle in the DB cards (an inference, not tested).** If Take control copies the generated config into a static storage dashboard, whatever the server sent to the person who took control becomes fixed. An administrator taking control would freeze the Settings view into a config every user can open. If the Settings view is stripped on the server and the generator then no longer writes a `visible` condition, the frozen copy would not hide it. Keeping a `visible` user condition on the Settings view as well as the server decision would cover that case. Check it with the manual Take control test below.

## Cannot verify offline (frontend)

The e2e environment has no `hass_frontend` package (`pip list` shows no `home-assistant-frontend`; `homeassistant/components/frontend/manifest.json` pins `home-assistant-frontend==20260826.7` for 2026.9.4, and `test_the_frontend_package_is_not_installed_in_this_environment` records the absence). Everything below needs a browser on a Home Assistant instance with this integration. None of it was run.

| Item | Status | Manual check for the maintainer |
|---|---|---|
| `window.customStrategies` registration | cannot verify | The shipped strategy file (34 lines) does not touch `window.customStrategies`. Today, in the browser console on any Home Assistant page: `window.customStrategies` should be `undefined` (confirms the premise). After the dashboard cards add the registration, the same expression should list an entry with the strategy's name, and Settings, Dashboards, Add dashboard, Community dashboards should show it. The exact fields of the entry come from the Home Assistant developer documentation on custom strategies, which was not read for this spike |
| `getCreateSuggestions` | cannot verify | After the static method is added, picking the Community dashboards entry should pre-fill the title (GivEnergy) and icon (`mdi:solar-power-variant`) in the create dialog. If the dialog is blank, the suggestions are not read for custom strategies |
| Take control | cannot verify | Create a dashboard from scratch, open Raw configuration editor and set `strategy:` with `type: custom:givenergy-manager`. Open it, open the three-dot menu and look for Take control. If present, use it, then check the dashboard is static, still renders, and whether the Settings view is visible to a non-admin user (the design risk above) |
| Distribution card with our entities | cannot verify | On the target version (2026.5 floor and latest): Edit dashboard, Add card, search for Distribution. Add it with the entities the Overview would use (solar, battery, grid, house, immersion, EV power sensors) and note whether it accepts them and how it labels them |

Decision these checks feed (brief section 12, SP2 row): if Take control does not work for custom strategies, the dashboard docs say "copy to a personal dashboard"; if the distribution card rejects our entities, the Overview uses tiles only.

## Decision

- **Server-side admin check: go.** Read `connection.user.is_admin` in the existing handler and pass a boolean, as described. No fallback (a server-side administrator list) is needed.
- **Frontend items: keep the plan, gated on the manual checks above**, which the maintainer runs before the DB cards that depend on them (DB3 and DB4 in the brief). The strategy file is not changed in this PR.

## Not verified

- Floor 2026.5.0 and the latest release: only 2026.9.4 is installed.
- Everything in the frontend table.
- That the read-only user in the harness behaves like a real non-admin user with a real long-lived session; the tests use the plugin's mock users and tokens.

## Manual checks, run on 13 October 2026

Run in a browser on Home Assistant 2026.10.1 with the integration at 0.19.0b5. The version floor, 2026.5.0, was not run in a browser.

| Item | Result |
|---|---|
| `window.customStrategies` registration | **Registered.** The console lists the strategy with `type: givenergy-manager`, `strategyType: dashboard`, the name GivEnergy, a description and a documentation URL. The premise above (`undefined` today) no longer holds: the strategy registers itself |
| Community dashboards listing | **Works.** GivEnergy is listed with its description under Community dashboards in **Add dashboard** |
| Creating from the strategy | **Works**, both from that entry and from the raw configuration `strategy: {type: custom:givenergy-manager}` |
| Take control | **Offered and works** on a dashboard made from the strategy. The Settings view for a non-administrator after taking control was not tested. The Settings view keeps its `visible` user list, which covers it |
| Distribution card | **Accepts** the solar, battery, grid, house load, immersion and EV power sensors. It is a share-of-total bar over positive values, so mixing sources and consumers is misleading. Zero and negative values are greyed out and left out of the bar |
| `getCreateSuggestions` | Not separately tested. The create dialog showed the name and description. Whether the title and icon were pre-filled was not reported |

Decision: Take control works, so the dashboard docs do not say "copy to a personal dashboard". The distribution card does not reject the entities, but the Overview does not use it, so it is documented as an optional card only.
