"""The dashboard strategy against a real Home Assistant: websocket command, file route, module URL."""

from __future__ import annotations

import logging

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component

from custom_components.givenergy_inverter_manager.const import DOMAIN, INTEGRATION_VERSION
from custom_components.givenergy_inverter_manager.strategy import (
    STRATEGY_FILE,
    STRATEGY_URL_PATH,
    WS_TYPE,
    async_dashboard_for_websocket,
    strategy_module_url,
)
from tests.dashboard_support import default_entity_ids


async def test_websocket_command_returns_the_dashboard(hass, loaded_entry, hass_ws_client):
    # loaded_entry freezes the clock, so it must come before hass_ws_client creates its token.
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": WS_TYPE})
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"] == await async_dashboard_for_websocket(hass, is_admin=True)
    views = response["result"]["views"]
    tabs = [v["path"] for v in views if not v.get("subview")]
    assert tabs[:3] == ["power-flow", "today", "plan"]
    assert tabs[-1] == "bill"
    assert set(tabs) <= {"power-flow", "today", "plan", "tomorrow", "bill"}
    assert {v["type"] for v in views} == {"sections"}
    sub_views = {v["path"] for v in views if v.get("subview")}
    assert sub_views <= {"immersion", "ev-charger", "settings"}
    assert "settings" in sub_views


async def test_websocket_command_reports_when_the_entry_is_not_loaded(
    hass, loaded_entry, hass_ws_client
):
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": WS_TYPE})
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "not_found"


async def test_websocket_command_sees_changed_options_without_regenerating(
    hass, loaded_entry, hass_ws_client
):
    """The strategy builds the dashboard on each request, so a tariff edit shows at once."""
    from custom_components.givenergy_inverter_manager.const import CONF_BASE_RATE

    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_BASE_RATE: 0.4321}
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": WS_TYPE})
    response = await client.receive_json()

    view = next(v for v in response["result"]["views"] if v["path"] == "bill")
    tariff = next(s for s in view["sections"] if s["cards"][0].get("heading") == "Tariff")
    card = next(c for c in tariff["cards"] if c["type"] == "markdown")["content"]
    report = default_entity_ids()["tariff_in_use"]
    # The card reads the report sensor, which holds the new rate, so the card text never does.
    assert report in card
    assert "€0.4321" in hass.states.get(report).attributes["html"]
    assert "0.4321" not in card


async def test_strategy_file_is_served_and_added_to_the_frontend(
    hass, hass_in_scenario, service_calls, config_entry, hass_client, caplog
):
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda action, url: None, [])
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {strategy_module_url(hass)}

    client = await hass_client()
    response = await client.get(STRATEGY_URL_PATH)
    assert response.status == 200
    assert await response.text() == STRATEGY_FILE.read_text(encoding="utf-8")

    caplog.set_level(logging.WARNING)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert "Could not serve" not in caplog.text
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {strategy_module_url(hass)}
    assert (await client.get(STRATEGY_URL_PATH)).status == 200


async def test_the_strategy_is_added_to_the_frontend_before_any_entry_is_set_up(
    hass, hass_in_scenario, service_calls
):
    """A page served while the entry is still loading must already carry the script."""
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda action, url: None, [])
    assert await async_setup_component(hass, "http", {})

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {strategy_module_url(hass)}


async def test_the_browser_checks_its_copy_of_the_strategy_file_before_using_it(
    hass, hass_in_scenario, service_calls, config_entry, hass_client
):
    """A long cache lifetime kept a wrong response for weeks, so an ordinary refresh did not
    mend it. The file is kept but checked first, and the unchanged file costs a 304."""
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(STRATEGY_URL_PATH)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-cache"
    assert "max-age" not in response.headers["Cache-Control"]
    assert response.headers["Content-Type"].split(";")[0] in {
        "text/javascript",
        "application/javascript",
    }
    assert await response.text() == STRATEGY_FILE.read_text(encoding="utf-8")

    unchanged = await client.get(STRATEGY_URL_PATH, headers={"If-None-Match": response.headers["ETag"]})
    assert unchanged.status == 304


async def test_the_module_address_carries_the_version_and_is_the_same_at_every_start(
    hass, hass_in_scenario, service_calls, config_entry
):
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda action, url: None, [])
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    url = strategy_module_url(hass)
    assert url == f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}"
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {url}


class _StoredResources:
    """The stored resource collection Lovelace puts in hass.data, as far as the strategy uses it."""

    def __init__(self, items=None):
        self.items = list(items or [])

    async def async_get_info(self):
        return {"resources": len(self.items)}

    def async_items(self):
        return self.items

    async def async_create_item(self, data):
        item = {"id": f"id{len(self.items) + 1}", "type": data["res_type"], "url": data["url"]}
        self.items.append(item)
        return item

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]


def _with_lovelace_resources(hass, resources):
    from types import SimpleNamespace

    hass.data["lovelace"] = SimpleNamespace(resources=resources)


async def test_the_script_is_a_lovelace_resource_for_pages_served_before_setup(
    hass, hass_in_scenario, service_calls, config_entry
):
    """The page reads the resource list over the websocket, so a page served without the
    script in it still loads it."""
    resources = _StoredResources()
    _with_lovelace_resources(hass, resources)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert resources.items == [
        {"id": "id1", "type": "module", "url": f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}"}
    ]

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(resources.items) == 1


async def test_a_resource_of_an_older_release_is_replaced_at_setup(
    hass, hass_in_scenario, service_calls, config_entry
):
    resources = _StoredResources(
        [{"id": "old", "type": "module", "url": f"{STRATEGY_URL_PATH}?v=0.1.0&boot=1"}]
    )
    _with_lovelace_resources(hass, resources)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert [i["url"] for i in resources.items] == [f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}"]


async def test_removing_the_last_entry_takes_the_resource_out(
    hass, hass_in_scenario, service_calls, config_entry
):
    resources = _StoredResources()
    _with_lovelace_resources(hass, resources)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(resources.items) == 1

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert resources.items == []


async def test_setup_without_a_frontend_still_serves_the_file(
    hass, hass_in_scenario, service_calls, config_entry, hass_client
):
    """No frontend component: the file route exists but nothing is added to the frontend."""
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert DATA_EXTRA_MODULE_URL not in hass.data
    client = await hass_client()
    assert (await client.get(STRATEGY_URL_PATH)).status == 200
