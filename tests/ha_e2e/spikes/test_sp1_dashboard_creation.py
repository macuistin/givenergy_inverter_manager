"""Spike SP1: can an integration create, rename and delete a persistent storage dashboard?

Everything here runs against the real ``lovelace`` component of the pinned Home Assistant, with
the harness's storage mock (``hass_storage``) standing in for ``.storage``. The ``frontend``
component is not set up (its package is not installed, see SP2): the lovelace component
registers its panels through ``frontend.async_register_built_in_panel`` and that works without it.

Routes tried (docs/design/spikes/SP1.md):

* A. the admin websocket command ``lovelace/dashboards/create``, from a websocket client and
     dispatched in-process from integration code;
* B. instantiating ``DashboardsCollection`` ourselves, and reaching the live one;
* C. registering a ``LovelaceStorage`` and a panel directly (the ephemeral route).

Nothing under custom_components/ is used.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import DashboardsCollection
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.components.websocket_api.const import DOMAIN as WS_DOMAIN
from homeassistant.components.websocket_api.http import WebSocketAdapter
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_test_home_assistant

POINTER = {"strategy": {"type": "custom:givenergy-manager"}}
CREATE = {
    "type": "lovelace/dashboards/create",
    "url_path": "givenergy",
    "title": "GivEnergy",
    "icon": "mdi:solar-power-variant",
    "allow_single_word": True,
}


def _fields(**over: Any) -> dict[str, Any]:
    return {
        "url_path": "givenergy",
        "title": "GivEnergy",
        "icon": "mdi:solar-power-variant",
        "allow_single_word": True,
    } | over


@pytest.fixture
async def lovelace(hass: HomeAssistant) -> HomeAssistant:
    """The real lovelace component, set up with an empty configuration."""
    assert await async_setup_component(hass, "lovelace", {})
    await hass.async_block_till_done()
    return hass


async def _flush(hass: HomeAssistant) -> None:
    """Write out the delayed store saves the collection schedules, as a shutdown does."""
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()


@asynccontextmanager
async def _restart(hass: HomeAssistant) -> AsyncIterator[HomeAssistant]:
    """A second Home Assistant over the same (mocked) storage, with lovelace set up fresh."""
    await _flush(hass)
    async with async_test_home_assistant(config_dir=hass.config.config_dir) as second:
        frame.async_setup(second)
        try:
            assert await async_setup_component(second, "lovelace", {})
            await second.async_block_till_done()
            yield second
        finally:
            await second.async_stop(force=True)
            frame.async_setup(hass)


async def _ask(client, msg_id: int, **msg: Any) -> dict:
    await client.send_json({"id": msg_id, **msg})
    return await client.receive_json()


def _panel(hass: HomeAssistant, url_path: str) -> frontend.Panel | None:
    return hass.data.get(frontend.DATA_PANELS, {}).get(url_path)


def _store(hass_storage: dict, key: str) -> dict | None:
    return (hass_storage.get(key) or {}).get("data")


# ---------------------------------------------------------------------------------------------
# The component under test
# ---------------------------------------------------------------------------------------------


async def test_lovelace_is_the_real_component_and_runs_without_the_frontend_package(lovelace):
    hass = lovelace
    assert "frontend" not in hass.config.components
    assert importlib.util.find_spec("hass_frontend") is None
    assert set(hass.data[LOVELACE_DATA].dashboards) == {None}
    assert _panel(hass, "lovelace") is not None
    assert "lovelace/dashboards/create" in hass.data[WS_DOMAIN]


# ---------------------------------------------------------------------------------------------
# Route A: the admin websocket command
# ---------------------------------------------------------------------------------------------


async def test_a_url_path_without_a_hyphen_needs_allow_single_word(lovelace, hass_ws_client):
    client = await hass_ws_client(lovelace)
    without = {k: v for k, v in CREATE.items() if k != "allow_single_word"}
    response = await _ask(client, 1, **without)
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"
    assert "Url path needs to contain a hyphen (-)" in response["error"]["message"]
    assert _panel(lovelace, "givenergy") is None

    response = await _ask(client, 2, **CREATE)
    assert response["success"] is True
    assert response["result"] == {
        "id": "givenergy",
        "url_path": "givenergy",
        "title": "GivEnergy",
        "icon": "mdi:solar-power-variant",
        "require_admin": False,
        "show_in_sidebar": True,
        "mode": "storage",
    }  # allow_single_word is consumed, not stored


async def test_a_created_dashboard_is_a_visible_sidebar_panel_listed_in_settings(
    lovelace, hass_ws_client
):
    hass = lovelace
    client = await hass_ws_client(hass)
    assert (await _ask(client, 1, **CREATE))["success"]

    panel = _panel(hass, "givenergy")
    assert panel is not None
    assert panel.component_name == "lovelace"
    assert panel.sidebar_title == "GivEnergy"
    assert panel.sidebar_icon == "mdi:solar-power-variant"
    assert panel.require_admin is False
    assert panel.show_in_sidebar is True
    assert panel.config == {"mode": "storage"}
    assert "givenergy" in hass.data[LOVELACE_DATA].dashboards

    listed = await _ask(client, 2, type="lovelace/dashboards/list")
    assert [d["url_path"] for d in listed["result"]] == ["givenergy"]


async def test_a_strategy_pointer_can_be_saved_and_read_back(lovelace, hass_ws_client):
    client = await hass_ws_client(lovelace)
    assert (await _ask(client, 1, **CREATE))["success"]

    # Before a config is saved the dashboard is auto-generated: there is nothing to read.
    assert await lovelace.data[LOVELACE_DATA].dashboards["givenergy"].async_get_info() == {
        "mode": "auto-gen"
    }
    missing = await _ask(client, 3, type="lovelace/config", url_path="givenergy", force=False)
    assert missing["success"] is False
    assert missing["error"]["code"] == "config_not_found"

    saved = await _ask(client, 4, type="lovelace/config/save", url_path="givenergy", config=POINTER)
    assert saved["success"] is True
    read = await _ask(client, 5, type="lovelace/config", url_path="givenergy", force=False)
    assert read["result"] == POINTER
    # The pointer can also be written from integration code, as core does for its map dashboard
    # (lovelace/__init__.py `_create_map_dashboard`).
    store = lovelace.data[LOVELACE_DATA].dashboards["givenergy"]
    await store.async_save({"strategy": {"type": "custom:givenergy-manager", "n": 2}})
    read = await _ask(client, 6, type="lovelace/config", url_path="givenergy", force=False)
    assert read["result"]["strategy"]["n"] == 2


async def test_a_rename_updates_the_panel_and_keeps_the_pointer(lovelace, hass_ws_client):
    hass = lovelace
    client = await hass_ws_client(hass)
    assert (await _ask(client, 1, **CREATE))["success"]
    await _ask(client, 2, type="lovelace/config/save", url_path="givenergy", config=POINTER)

    renamed = await _ask(
        client,
        3,
        type="lovelace/dashboards/update",
        dashboard_id="givenergy",
        title="Home energy",
        icon="mdi:flash",
    )
    assert renamed["success"] is True
    assert renamed["result"]["title"] == "Home energy"
    assert _panel(hass, "givenergy").sidebar_title == "Home energy"
    assert _panel(hass, "givenergy").sidebar_icon == "mdi:flash"
    read = await _ask(client, 4, type="lovelace/config", url_path="givenergy", force=False)
    assert read["result"] == POINTER
    # The url path is not an updatable field.
    bad = await _ask(
        client, 5, type="lovelace/dashboards/update", dashboard_id="givenergy", url_path="other-x"
    )
    assert bad["success"] is False


async def test_a_delete_removes_the_panel_the_item_and_the_stored_config(
    lovelace, hass_ws_client, hass_storage
):
    hass = lovelace
    client = await hass_ws_client(hass)
    assert (await _ask(client, 1, **CREATE))["success"]
    await _ask(client, 2, type="lovelace/config/save", url_path="givenergy", config=POINTER)
    await _flush(hass)
    assert _store(hass_storage, "lovelace.givenergy") == {"config": POINTER}
    assert [i["id"] for i in _store(hass_storage, "lovelace_dashboards")["items"]] == ["givenergy"]

    deleted = await _ask(client, 3, type="lovelace/dashboards/delete", dashboard_id="givenergy")
    assert deleted["success"] is True
    await _flush(hass)
    assert _panel(hass, "givenergy") is None
    assert "givenergy" not in hass.data[LOVELACE_DATA].dashboards
    assert "lovelace.givenergy" not in hass_storage
    assert _store(hass_storage, "lovelace_dashboards")["items"] == []


async def test_a_create_is_admin_only(lovelace, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(lovelace, hass_read_only_access_token)
    response = await _ask(client, 1, **CREATE)
    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert _panel(lovelace, "givenergy") is None


async def test_a_create_refuses_a_url_path_another_panel_already_uses(lovelace, hass_ws_client):
    hass = lovelace
    frontend.async_register_built_in_panel(
        hass, "iframe", frontend_url_path="givenergy", sidebar_title="Taken"
    )
    client = await hass_ws_client(hass)
    response = await _ask(client, 1, **CREATE)
    assert response["success"] is False
    assert response["error"]["code"] == "home_assistant_error"
    assert _panel(hass, "givenergy").component_name == "iframe"
    assert hass.data[LOVELACE_DATA].dashboards.keys() == {None}


async def test_a_create_and_pointer_and_rename_survive_a_restart(
    lovelace, hass_ws_client, hass_storage
):
    hass = lovelace
    client = await hass_ws_client(hass)
    assert (await _ask(client, 1, **CREATE))["success"]
    await _ask(client, 2, type="lovelace/config/save", url_path="givenergy", config=POINTER)
    await _ask(client, 3, type="lovelace/dashboards/update", dashboard_id="givenergy", title="Mine")

    async with _restart(hass) as second:
        panel = _panel(second, "givenergy")
        assert panel is not None
        assert panel.sidebar_title == "Mine"  # a rename is respected, not reset
        assert panel.sidebar_icon == "mdi:solar-power-variant"
        assert await second.data[LOVELACE_DATA].dashboards["givenergy"].async_load(False) == POINTER
        items = second.data[LOVELACE_DATA].dashboards["givenergy"].config
        assert items["title"] == "Mine"


async def test_a_dashboard_the_user_deleted_stays_deleted_after_a_restart(lovelace, hass_ws_client):
    client = await hass_ws_client(lovelace)
    assert (await _ask(client, 1, **CREATE))["success"]
    await _flush(lovelace)  # the dashboard is on disk before the user deletes it
    assert (await _ask(client, 2, type="lovelace/dashboards/delete", dashboard_id="givenergy"))[
        "success"
    ]
    async with _restart(lovelace) as second:
        assert _panel(second, "givenergy") is None
        assert set(second.data[LOVELACE_DATA].dashboards) == {None}


async def test_a_in_process_dispatch_of_the_command_needs_an_admin_identity(
    lovelace, hass_admin_user, hass_read_only_user
):
    """Integration code can drive the command through its own ActiveConnection.

    The command is checked against the connection's user, so the call works only when the
    integration hands it an admin user. The same code path as a websocket client is used.
    """
    hass = lovelace
    sent: list[dict] = []

    def _send(message: bytes | str | dict) -> None:
        sent.append(json.loads(message) if isinstance(message, bytes | str) else message)

    def _connection(user) -> ActiveConnection:
        logger = WebSocketAdapter(logging.getLogger("sp1"), {"connid": "sp1"})
        return ActiveConnection(logger, hass, _send, user, None, None)

    _connection(hass_read_only_user).async_handle({"id": 1, **CREATE})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sent[-1]["success"] is False
    assert sent[-1]["error"]["code"] == "unauthorized"
    assert _panel(hass, "givenergy") is None

    _connection(hass_admin_user).async_handle({"id": 1, **CREATE})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sent[-1]["success"] is True
    assert sent[-1]["result"]["url_path"] == "givenergy"
    assert _panel(hass, "givenergy").sidebar_title == "GivEnergy"
    assert "givenergy" in hass.data[LOVELACE_DATA].dashboards


# ---------------------------------------------------------------------------------------------
# Route B: the collection
# ---------------------------------------------------------------------------------------------


async def test_b_the_collection_is_not_in_hass_data(lovelace):
    """It is a local variable of lovelace.async_setup: nothing to look up."""
    data = lovelace.data[LOVELACE_DATA]
    assert not any(isinstance(v, DashboardsCollection) for v in vars(data).values())
    assert not any(isinstance(v, DashboardsCollection) for v in lovelace.data.values())


async def test_b_our_own_collection_instance_is_invisible_to_the_running_component(
    lovelace, hass_ws_client
):
    hass = lovelace
    ours = DashboardsCollection(hass)
    await ours.async_load()
    await ours.async_create_item(_fields())
    assert [i["url_path"] for i in ours.async_items()] == ["givenergy"]

    # No listener ran: no panel, no LovelaceStorage, not in the list the UI shows.
    assert _panel(hass, "givenergy") is None
    assert "givenergy" not in hass.data[LOVELACE_DATA].dashboards
    client = await hass_ws_client(hass)
    assert (await _ask(client, 1, type="lovelace/dashboards/list"))["result"] == []


async def test_b_an_item_written_by_our_own_collection_is_overwritten_by_the_live_one(
    lovelace, hass_ws_client, hass_storage
):
    hass = lovelace
    ours = DashboardsCollection(hass)
    await ours.async_load()
    await ours.async_create_item(_fields())
    await _flush(hass)
    assert [i["url_path"] for i in _store(hass_storage, "lovelace_dashboards")["items"]] == [
        "givenergy"
    ]

    # The user adds any dashboard in the UI: the live collection saves its own item list.
    client = await hass_ws_client(hass)
    other = await _ask(client, 1, **dict(CREATE, url_path="user-made", title="Mine"))
    assert other["success"]
    await _flush(hass)
    assert [i["url_path"] for i in _store(hass_storage, "lovelace_dashboards")["items"]] == [
        "user-made"
    ]


async def test_b_the_live_collection_is_reachable_by_unwrapping_a_registered_handler(
    lovelace,
):
    """Possible on this version, and only by reflection on private attributes."""
    hass = lovelace
    list_handler = hass.data[WS_DOMAIN]["lovelace/dashboards/list"][0]
    live = list_handler.__self__.storage_collection
    assert isinstance(live, DashboardsCollection)

    await live.async_create_item(_fields())
    await hass.async_block_till_done()
    assert _panel(hass, "givenergy").sidebar_title == "GivEnergy"
    assert "givenergy" in hass.data[LOVELACE_DATA].dashboards


# ---------------------------------------------------------------------------------------------
# Route C: the ephemeral panel
# ---------------------------------------------------------------------------------------------


async def _register_ephemeral(hass: HomeAssistant) -> None:
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    config = {
        "id": "givenergy",
        "url_path": "givenergy",
        "title": "GivEnergy",
        "icon": "mdi:solar-power-variant",
        "require_admin": False,
        "show_in_sidebar": True,
        "mode": "storage",
    }
    store = LovelaceStorage(hass, config)
    hass.data[LOVELACE_DATA].dashboards["givenergy"] = store
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title="GivEnergy",
        sidebar_icon="mdi:solar-power-variant",
        frontend_url_path="givenergy",
        config={"mode": "storage"},
    )
    await store.async_save(POINTER)


async def test_c_the_ephemeral_route_renders_but_the_ui_cannot_manage_it(
    lovelace, hass_ws_client, hass_storage
):
    hass = lovelace
    await _register_ephemeral(hass)
    client = await hass_ws_client(hass)

    read = await _ask(client, 1, type="lovelace/config", url_path="givenergy", force=False)
    assert read["result"] == POINTER
    # The settings list shows it (it lists the live LovelaceStorage objects) ...
    listed = await _ask(client, 2, type="lovelace/dashboards/list")
    assert [d["url_path"] for d in listed["result"]] == ["givenergy"]
    # ... but the collection never heard of it, so rename and delete from the UI fail.
    for msg_id, msg in (
        (3, {"type": "lovelace/dashboards/update", "dashboard_id": "givenergy", "title": "X"}),
        (4, {"type": "lovelace/dashboards/delete", "dashboard_id": "givenergy"}),
    ):
        response = await _ask(client, msg_id, **msg)
        assert response["success"] is False
        assert response["error"]["code"] == "not_found"
    await _flush(hass)
    assert not (_store(hass_storage, "lovelace_dashboards") or {}).get("items")


async def test_c_the_ephemeral_route_is_gone_after_a_restart_and_leaves_an_orphan_file(
    lovelace, hass_storage
):
    hass = lovelace
    await _register_ephemeral(hass)
    async with _restart(hass) as second:
        assert _panel(second, "givenergy") is None
        assert "givenergy" not in second.data[LOVELACE_DATA].dashboards
    assert _store(hass_storage, "lovelace.givenergy") == {"config": POINTER}  # orphaned
