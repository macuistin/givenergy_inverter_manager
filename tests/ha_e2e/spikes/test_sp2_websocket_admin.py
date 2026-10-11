"""Spike SP2: what can be proved offline about the server-side admin decision.

Proved here (docs/design/spikes/SP2.md):

* ``connection.user.is_admin`` is available in a custom websocket handler written the way
  ``strategy.py`` writes its handler, for an administrator and for a read-only user;
* the handler's schema decides what happens to extra client fields (rejected by the existing
  schema, ignored by a schema that allows extras), and neither lets a client claim admin;
* a role change shows on the next message of a connection that is already open;
* the real command once sent the Settings view to a read-only user as well, relying on the
  frontend to hide it. The server-side decision closed that gap, and the last test now pins
  the closed state.

Not provable here: Take control, ``getCreateSuggestions``, ``window.customStrategies`` and the
distribution card are frontend behaviour, and the frontend package is not installed in this
environment. The note lists the manual checks.
"""

from __future__ import annotations

import importlib.util

import pytest
import voluptuous as vol
from conftest import MIDDAY
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_READ_ONLY
from homeassistant.components import websocket_api

from custom_components.givenergy_inverter_manager.strategy import WS_TYPE

PROBE = "sp2_probe/who"
PROBE_LOOSE = "sp2_probe/who_loose"


def _register_probe(hass) -> None:
    """The same decorator shape as strategy.py's ws_dashboard, reading connection.user."""

    @websocket_api.websocket_command({vol.Required("type"): PROBE})
    @websocket_api.async_response
    async def ws_probe(hass, connection, msg):
        connection.send_result(msg["id"], {"is_admin": connection.user.is_admin})

    @websocket_api.websocket_command(
        {vol.Required("type"): PROBE_LOOSE},
    )
    @websocket_api.async_response
    async def ws_probe_loose(hass, connection, msg):
        # Reads the user from the connection and never from the message.
        connection.send_result(
            msg["id"], {"is_admin": connection.user.is_admin, "keys_seen": sorted(msg)}
        )

    websocket_api.async_register_command(hass, ws_probe)
    # A schema that tolerates unknown keys, to show they are ignored rather than trusted.
    websocket_api.async_register_command(
        hass,
        PROBE_LOOSE,
        ws_probe_loose,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): PROBE_LOOSE}, extra=vol.ALLOW_EXTRA
        ),
    )


async def _ask(client, msg_id: int, **msg) -> dict:
    await client.send_json({"id": msg_id, **msg})
    return await client.receive_json()


@pytest.fixture
def scenario():
    return MIDDAY


# ---------------------------------------------------------------------------------------------
# connection.user.is_admin in a handler shaped like strategy.py's
# ---------------------------------------------------------------------------------------------


async def test_handler_reads_is_admin_for_an_admin_and_for_a_read_only_user(
    hass, hass_ws_client, hass_read_only_access_token
):
    _register_probe(hass)
    admin = await hass_ws_client(hass)
    read_only = await hass_ws_client(hass, hass_read_only_access_token)

    assert (await _ask(admin, 1, type=PROBE))["result"] == {"is_admin": True}
    assert (await _ask(read_only, 1, type=PROBE))["result"] == {"is_admin": False}


async def test_the_existing_schema_rejects_extra_client_fields(hass, hass_ws_client):
    """strategy.py's schema is {Required("type"): ...}: an `admin` claim is an error."""
    _register_probe(hass)
    client = await hass_ws_client(hass)
    response = await _ask(client, 1, type=PROBE, admin=True, is_admin=True)
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


async def test_a_schema_that_allows_extras_ignores_a_claimed_admin_flag(
    hass, hass_ws_client, hass_read_only_access_token
):
    _register_probe(hass)
    read_only = await hass_ws_client(hass, hass_read_only_access_token)
    response = await _ask(read_only, 1, type=PROBE_LOOSE, is_admin=True, admin=True, user_id="x")
    assert response["success"] is True
    assert response["result"]["is_admin"] is False
    # The extra keys reached the handler as data and the handler did not use them.
    assert {"admin", "is_admin", "user_id"} <= set(response["result"]["keys_seen"])


async def test_a_role_change_shows_on_the_next_message_of_an_open_connection(
    hass, hass_ws_client, hass_read_only_access_token, hass_read_only_user
):
    _register_probe(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _ask(client, 1, type=PROBE))["result"] == {"is_admin": False}

    await hass.auth.async_update_user(hass_read_only_user, group_ids=[GROUP_ID_ADMIN])
    assert (await _ask(client, 2, type=PROBE))["result"] == {"is_admin": True}

    await hass.auth.async_update_user(hass_read_only_user, group_ids=[GROUP_ID_READ_ONLY])
    assert (await _ask(client, 3, type=PROBE))["result"] == {"is_admin": False}


async def test_a_deactivated_administrator_is_not_an_admin(hass, hass_read_only_user):
    """is_admin includes is_active, so the check is stricter than the group alone."""
    await hass.auth.async_update_user(hass_read_only_user, group_ids=[GROUP_ID_ADMIN])
    assert hass_read_only_user.is_admin is True
    await hass.auth.async_update_user(hass_read_only_user, is_active=False)
    assert hass_read_only_user.is_admin is False


# ---------------------------------------------------------------------------------------------
# The real command today
# ---------------------------------------------------------------------------------------------


async def test_the_real_command_rejects_extra_client_fields(hass, loaded_entry, hass_ws_client):
    client = await hass_ws_client(hass)
    response = await _ask(client, 1, type=WS_TYPE, admin=True)
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


async def test_the_real_command_sends_the_settings_view_to_an_administrator_only(
    hass, loaded_entry, hass_ws_client, hass_read_only_access_token, hass_admin_user
):
    """The gap SP2 found, now closed: the server leaves Settings out for a read-only user.

    This test first pinned the gap (both clients got the view, with hiding left to the
    frontend's `visible` list). The server-side decision flipped it on purpose. The permanent
    tests are in tests/ha_e2e/test_dashboard_admin_e2e.py.
    """
    admin = await hass_ws_client(hass)
    read_only = await hass_ws_client(hass, hass_read_only_access_token)

    response = await _ask(admin, 1, type=WS_TYPE)
    settings = next(v for v in response["result"]["views"] if v["path"] == "settings")
    assert settings["visible"] == [{"user": hass_admin_user.id}]
    assert settings["sections"]

    response = await _ask(read_only, 1, type=WS_TYPE)
    assert response["success"] is True
    assert all(v["path"] != "settings" for v in response["result"]["views"])


# ---------------------------------------------------------------------------------------------
# What this environment cannot show
# ---------------------------------------------------------------------------------------------


def test_the_frontend_package_is_not_installed_in_this_environment():
    """Tripwire for the note: while this holds, the frontend checks stay manual."""
    if importlib.util.find_spec("hass_frontend") is not None:
        pytest.skip("hass_frontend is installed now: the frontend items in SP2.md can be checked")
    assert importlib.util.find_spec("hass_frontend") is None
