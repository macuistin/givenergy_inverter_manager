"""The dashboard strategy against a real Home Assistant: websocket command, file route, module URL."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.givenergy_inverter_manager.const import DOMAIN, INTEGRATION_VERSION
from custom_components.givenergy_inverter_manager.strategy import (
    STRATEGY_FILE,
    STRATEGY_URL_PATH,
    WS_TYPE,
)

MODULE_URL = f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}"


async def _service_dashboard(hass) -> dict:
    """What the get_dashboard_yaml service writes, parsed back into a dict."""
    async_mock_service(hass, "persistent_notification", "create")
    await hass.services.async_call(DOMAIN, "get_dashboard_yaml", blocking=True)
    await hass.async_block_till_done()
    text = (Path(hass.config.config_dir) / "givenergy_dashboard.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


async def test_websocket_command_returns_the_dashboard(hass, loaded_entry, hass_ws_client):
    # loaded_entry freezes the clock, so it must come before hass_ws_client creates its token.
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": WS_TYPE})
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"] == await _service_dashboard(hass)
    views = response["result"]["views"]
    assert [v["path"] for v in views if not v.get("subview")] == [
        "power-flow",
        "today",
        "bill",
        "battery",
        "controls",
    ]
    sub_views = {v["path"] for v in views if v.get("subview")}
    assert sub_views <= {"immersion", "ev-charger", "cost", "solar", "tariff", "battery-detail"}
    assert {"cost", "tariff", "battery-detail"} <= sub_views


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

    tariff = next(v for v in response["result"]["views"] if v["path"] == "tariff")
    table = next(c for c in tariff["cards"] if c["type"] == "markdown")["content"]
    assert "€0.4321" in table


async def test_strategy_file_is_served_and_added_to_the_frontend(
    hass, hass_in_scenario, service_calls, config_entry, hass_client, caplog
):
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda action, url: None, [])
    assert await async_setup_component(hass, "http", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {MODULE_URL}

    client = await hass_client()
    response = await client.get(STRATEGY_URL_PATH)
    assert response.status == 200
    assert await response.text() == STRATEGY_FILE.read_text(encoding="utf-8")

    caplog.set_level(logging.WARNING)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert "Could not serve" not in caplog.text
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {MODULE_URL}
    assert (await client.get(STRATEGY_URL_PATH)).status == 200


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
