"""The dashboard notice against a real Home Assistant with a real Lovelace.

The integration does not create the dashboard (docs/design/spikes/SP1.md). At first setup it
looks for one that uses the strategy and, when there is none, sends a notification that says
how to add it. The tests add dashboards the way a user does, through the dashboards websocket
commands, and check that a reload does not repeat the notification, that a deleted dashboard
stays deleted, and that removing the entry takes the notification down.
"""

from __future__ import annotations

import pytest
from homeassistant.components.persistent_notification import _async_get_or_create_notifications
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component

from custom_components.givenergy_inverter_manager.const import CONF_DASHBOARD_URL_PATH
from custom_components.givenergy_inverter_manager.dashboard_notice import (
    NOTIFICATION_ID,
    NOTIFICATION_MESSAGE,
)

POINTER = {"strategy": {"type": "custom:givenergy-manager"}}


def _notification(hass) -> dict | None:
    return _async_get_or_create_notifications(hass).get(NOTIFICATION_ID)


async def _ask(client, msg_id: int, **msg) -> dict:
    await client.send_json({"id": msg_id, **msg})
    return await client.receive_json()


@pytest.fixture
async def lovelace(hass_in_scenario, hass_ws_client):
    """Lovelace set up, and an administrator's websocket client to add dashboards with."""
    hass = hass_in_scenario
    assert await async_setup_component(hass, "lovelace", {})
    await hass.async_block_till_done()
    return await hass_ws_client(hass)


async def _add_dashboard(client, url_path: str, config: dict | None) -> None:
    created = await _ask(
        client,
        1,
        type="lovelace/dashboards/create",
        url_path=url_path,
        title="GivEnergy",
        allow_single_word=True,
    )
    assert created["success"], created
    if config is not None:
        saved = await _ask(client, 2, type="lovelace/config/save", url_path=url_path, config=config)
        assert saved["success"], saved


async def _set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _reload(hass, entry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_a_first_setup_with_no_dashboard_sends_the_notification(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _set_up(hass, config_entry)

    note = _notification(hass)
    assert note is not None
    assert note["message"] == NOTIFICATION_MESSAGE
    assert "Community dashboards" in note["message"]
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == ""


async def test_saving_the_answer_does_not_reload_the_entry(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _set_up(hass, config_entry)
    coordinator = config_entry.runtime_data

    await hass.async_block_till_done()

    assert config_entry.runtime_data is coordinator
    assert config_entry.state is ConfigEntryState.LOADED


async def test_a_reload_does_not_send_it_again(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _set_up(hass, config_entry)
    # The user reads it and dismisses it.
    del _async_get_or_create_notifications(hass)[NOTIFICATION_ID]

    await _reload(hass, config_entry)

    assert _notification(hass) is None
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == ""


async def test_a_dashboard_that_uses_the_strategy_is_found_and_nothing_is_sent(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "givenergy", POINTER)

    await _set_up(hass, config_entry)

    assert _notification(hass) is None
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == "givenergy"


async def test_a_dashboard_with_its_own_cards_is_not_ours(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "givenergy", {"views": [{"title": "Mine", "cards": []}]})

    await _set_up(hass, config_entry)

    assert _notification(hass) is not None
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == ""


async def test_a_dashboard_with_another_strategy_is_not_ours(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "other-home", {"strategy": {"type": "original-states"}})

    await _set_up(hass, config_entry)

    assert _notification(hass) is not None


async def test_a_dashboard_with_no_saved_config_is_not_ours(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "givenergy", None)

    await _set_up(hass, config_entry)

    assert _notification(hass) is not None


async def test_the_default_dashboard_can_use_the_strategy(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    saved = await _ask(lovelace, 1, type="lovelace/config/save", config=POINTER)
    assert saved["success"], saved

    await _set_up(hass, config_entry)

    assert _notification(hass) is None
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == "lovelace"


async def test_a_dashboard_the_user_deletes_stays_deleted(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "givenergy", POINTER)
    await _set_up(hass, config_entry)
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == "givenergy"

    deleted = await _ask(lovelace, 3, type="lovelace/dashboards/delete", dashboard_id="givenergy")
    assert deleted["success"], deleted
    await _reload(hass, config_entry)

    assert _notification(hass) is None
    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == "givenergy"


async def test_a_dashboard_added_later_is_not_needed_for_the_option_to_hold(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    """The user adds the dashboard after being told. The answer stays as it was."""
    hass = hass_in_scenario
    await _set_up(hass, config_entry)
    await _add_dashboard(lovelace, "givenergy", POINTER)

    await _reload(hass, config_entry)

    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == ""


async def test_without_lovelace_nothing_is_sent_and_nothing_is_saved(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    assert "lovelace" not in hass.data

    await _set_up(hass, config_entry)

    assert _notification(hass) is None
    assert CONF_DASHBOARD_URL_PATH not in config_entry.options


async def test_a_failure_while_looking_never_stops_setup(
    hass_in_scenario, service_calls, config_entry, lovelace, monkeypatch
):
    hass = hass_in_scenario

    async def broken(_hass):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.givenergy_inverter_manager.dashboard_notice.async_find_dashboard",
        broken,
    )
    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert CONF_DASHBOARD_URL_PATH not in config_entry.options


async def test_removing_the_entry_takes_the_notification_down(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _set_up(hass, config_entry)
    assert _notification(hass) is not None

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _notification(hass) is None


async def test_the_dashboard_the_user_added_survives_removal_of_the_entry(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    """The integration did not create the dashboard, so it never deletes one."""
    hass = hass_in_scenario
    await _add_dashboard(lovelace, "givenergy", POINTER)
    await _set_up(hass, config_entry)

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    listed = await _ask(lovelace, 9, type="lovelace/dashboards/list")
    assert [item["url_path"] for item in listed["result"]] == ["givenergy"]
