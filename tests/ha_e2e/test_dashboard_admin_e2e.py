"""The Settings view reaches administrators only, decided by the server from the connection.

A real websocket client for an administrator and for a read-only user ask the real command.
The dashboard each gets is what the integration builds for that user, so a viewer who is not an
administrator never holds the Settings view in the payload, whatever the frontend does with a
`visible` list.
"""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.strategy import WS_TYPE


async def _ask(client, msg_id: int, **msg) -> dict:
    await client.send_json({"id": msg_id, "type": WS_TYPE, **msg})
    return await client.receive_json()


def _paths(response: dict) -> list[str]:
    return [view["path"] for view in response["result"]["views"]]


async def test_an_administrator_gets_the_settings_view_and_its_button(
    hass, loaded_entry, hass_ws_client, hass_admin_user
):
    response = await _ask(await hass_ws_client(hass), 1)

    assert response["success"] is True
    settings = next(v for v in response["result"]["views"] if v["path"] == "settings")
    assert settings["visible"] == [{"user": hass_admin_user.id}]
    assert settings["sections"]
    assert "'navigation_path': 'settings'" in str(response["result"])


async def test_a_read_only_user_gets_no_settings_view_no_button_and_no_admin_id(
    hass, loaded_entry, hass_ws_client, hass_read_only_access_token, hass_admin_user
):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    response = await _ask(client, 1)

    assert response["success"] is True
    assert "settings" not in _paths(response)
    assert "'navigation_path': 'settings'" not in str(response["result"])
    assert hass_admin_user.id not in str(response["result"])


async def test_the_rest_of_the_dashboard_is_the_same_for_both(
    hass, loaded_entry, hass_ws_client, hass_read_only_access_token
):
    admin = await _ask(await hass_ws_client(hass), 1)
    read_only = await _ask(await hass_ws_client(hass, hass_read_only_access_token), 1)

    assert [p for p in _paths(admin) if p != "settings"] == _paths(read_only)


async def test_extra_fields_cannot_ask_for_the_settings_view(
    hass, loaded_entry, hass_ws_client, hass_read_only_access_token
):
    """The command accepts no field but its type, so a claimed flag is refused, not trusted."""
    client = await hass_ws_client(hass, hass_read_only_access_token)

    for msg_id, extra in enumerate(({"admin": True}, {"is_admin": True}, {"user": "owner"}), 1):
        response = await _ask(client, msg_id, **extra)
        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert "result" not in response


async def test_a_role_change_shows_on_the_next_request_of_an_open_connection(
    hass, loaded_entry, hass_ws_client, hass_read_only_access_token, hass_read_only_user
):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    assert "settings" not in _paths(await _ask(client, 1))

    await hass.auth.async_update_user(hass_read_only_user, group_ids=["system-admin"])
    assert "settings" in _paths(await _ask(client, 2))
