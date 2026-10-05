"""Check the dashboard generator against a real entity registry."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import yaml
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.givenergy_inverter_manager.const import DOMAIN
from tests.dashboard_support import all_cards, default_entity_ids


def _registered_id(registry, entry_id: str, key: str) -> str | None:
    for domain in ("sensor", "switch", "number"):
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{key}")
        if entity_id:
            return entity_id
    return None


async def test_default_entity_ids_match_the_live_registry(hass, loaded_entry):
    """The IDs in docs/dashboard-example.yaml are the ones Home Assistant really assigns."""
    registry = er.async_get(hass)
    wrong = {}
    for key, expected in default_entity_ids().items():
        actual = _registered_id(registry, loaded_entry.entry_id, key)
        if actual != expected:
            wrong[key] = (expected, actual)
    assert wrong == {}


# ── generated dashboard against the real registry ────────────────────────────

_OURS = re.compile(r"\b(?:sensor|switch|number)\.givenergy_inverter_manager_[a-z0-9_]+")


async def _generate(hass) -> tuple[str, list]:
    """Run the get_dashboard_yaml service and return the file and the notifications."""
    notifications = async_mock_service(hass, "persistent_notification", "create")
    await hass.services.async_call(DOMAIN, "get_dashboard_yaml", blocking=True)
    await hass.async_block_till_done()
    text = (Path(hass.config.config_dir) / "givenergy_dashboard.yaml").read_text(encoding="utf-8")
    return text, notifications


def _names(text: str) -> list[str]:
    """Section headings and tile names, which is what a person reads on the dashboard."""
    cards = all_cards(yaml.safe_load(text)["views"])
    return [
        c["heading"] if c["type"] == "heading" else c["name"]
        for c in cards
        if c["type"] in {"heading", "tile"}
    ]


def _usable_ids(hass, entry) -> set[str]:
    registry = er.async_get(hass)
    return {
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.disabled_by is None
    }


async def test_fresh_install_dashboard_points_only_at_enabled_entities(hass, loaded_entry):
    """Every entity in the generated file is registered and enabled."""
    text, notifications = await _generate(hass)
    referenced = set(_OURS.findall(text))
    assert referenced
    assert referenced <= _usable_ids(hass, loaded_entry)


async def test_fresh_install_leaves_out_forecast_accuracy_and_says_so(hass, loaded_entry):
    text, notifications = await _generate(hass)
    registry = er.async_get(hass)
    accuracy = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_yesterday_forecast_accuracy_pct"
    )
    assert registry.async_get(accuracy).disabled_by is not None
    assert accuracy not in text
    assert "Forecast accuracy yesterday" in text[: text.index("views:")]
    assert "Forecast accuracy yesterday" in notifications[0].data["message"]


async def test_features_from_the_config_entry_show_up(hass, loaded_entry):
    """The full config has immersion, inverter temperature and a forecast, but no EV charger."""
    text, _ = await _generate(hass)
    names = _names(text)
    assert "Immersion heater" in names
    assert "Against the forecast" in names
    assert "EV charger" not in names
    assert "inverter_temperature" in text


async def test_external_ev_charger_adds_the_ev_card(hass, loaded_entry):
    hass.states.async_set("sensor.wallbox_charging_power", "0")
    text, _ = await _generate(hass)
    assert "EV charger" in _names(text)
    assert "sensor.wallbox_charging_power" in text


async def test_enabling_a_sensor_puts_it_back_in_the_dashboard(hass, loaded_entry):
    registry = er.async_get(hass)
    accuracy = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_yesterday_forecast_accuracy_pct"
    )
    registry.async_update_entity(accuracy, disabled_by=None)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED

    text, _ = await _generate(hass)
    assert accuracy in text


async def _setup_lovelace(hass):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "lovelace", {})
    await hass.async_block_till_done()
    return hass.data["lovelace"].resources


async def test_resources_are_read_from_a_real_lovelace(hass, loaded_entry):
    from custom_components.givenergy_inverter_manager.dashboard_builder import (
        async_lovelace_resource_urls,
    )

    resources = await _setup_lovelace(hass)
    assert await async_lovelace_resource_urls(hass) == []
    await resources.async_create_item(
        {"res_type": "module", "url": "/hacsfiles/apexcharts-card/apexcharts-card.js"}
    )
    assert await async_lovelace_resource_urls(hass) == [
        "/hacsfiles/apexcharts-card/apexcharts-card.js"
    ]


async def test_resources_are_none_without_lovelace(hass, loaded_entry):
    from custom_components.givenergy_inverter_manager.dashboard_builder import (
        async_lovelace_resource_urls,
    )

    assert "lovelace" not in hass.data
    assert await async_lovelace_resource_urls(hass) is None


async def test_generated_file_falls_back_when_cards_are_not_registered(hass, loaded_entry):
    await _setup_lovelace(hass)
    text, _ = await _generate(hass)
    assert "custom:power-flow-card-plus" not in text
    assert "custom:apexcharts-card" not in text
    assert "not installed" in text[: text.index("views:")]


async def test_generated_file_keeps_the_cards_that_are_registered(hass, loaded_entry):
    resources = await _setup_lovelace(hass)
    for url in (
        "/hacsfiles/power-flow-card-plus/power-flow-card-plus.js",
        "/hacsfiles/apexcharts-card/apexcharts-card.js",
    ):
        await resources.async_create_item({"res_type": "module", "url": url})
    text, _ = await _generate(hass)
    assert "custom:power-flow-card-plus" in text
    assert "custom:apexcharts-card" in text
    assert "not installed" not in text


async def test_live_dashboard_matches_the_docs_example(hass, loaded_entry):
    """Full config, every sensor enabled and an EV charger: the output is the docs example."""
    from types import SimpleNamespace

    from custom_components.givenergy_inverter_manager.const import CONF_BILL_START_DAY

    # The e2e config bills from day 16. The example uses the default, day 1.
    hass.config_entries.async_update_entry(
        loaded_entry, data={**loaded_entry.data, CONF_BILL_START_DAY: 1}
    )
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(registry, loaded_entry.entry_id):
        if entry.disabled_by is not None:
            registry.async_update_entity(entry.entity_id, disabled_by=None)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED
    loaded_entry.runtime_data._ev_charger = SimpleNamespace(brand=SimpleNamespace(value="myenergi"))

    text, _ = await _generate(hass)

    example = Path(__file__).parents[2] / "docs" / "dashboard-example.yaml"
    assert text == example.read_text(encoding="utf-8")
