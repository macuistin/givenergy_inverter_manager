"""Check the dashboard generator against a real entity registry."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import yaml
from conftest import ZAPPI_STATES, discover_the_charger
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.dashboard.devices import (
    expected_entity_id,
)
from tests.dashboard_support import (
    ADMIN_ID,
    all_cards,
    default_entity_ids,
    keys_needing_devices,
    view_cards,
)
from tests.dashboard_visibility import seen


def _registered_id(registry, entry_id: str, key: str) -> str | None:
    for domain in ("sensor", "switch", "number"):
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{key}")
        if entity_id:
            return entity_id
    return None


async def test_default_entity_ids_match_the_live_registry(hass, loaded_entry_with_charger):
    """The IDs in docs/dashboard-example.yaml are the ones Home Assistant really assigns."""
    registry = er.async_get(hass)
    wrong = {}
    for key, expected in default_entity_ids().items():
        actual = _registered_id(registry, loaded_entry_with_charger.entry_id, key)
        if actual != expected:
            wrong[key] = (expected, actual)
    assert wrong == {}


async def test_the_ids_a_stored_file_waits_on_are_the_ones_the_devices_get(
    hass, loaded_entry_with_charger
):
    """A card for a device that is not there yet names the ID Home Assistant will assign."""
    registry = er.async_get(hass)
    entry_id = loaded_entry_with_charger.entry_id
    for key in keys_needing_devices():
        assert expected_entity_id(key) == _registered_id(registry, entry_id, key), key


# ── generated dashboard against the real registry ────────────────────────────

_OURS = re.compile(r"\b(?:sensor|switch|number)\.givenergy_inverter_manager_[a-z0-9_]+")


async def _generate(hass) -> tuple[str, list]:
    """Run the get_dashboard_yaml service and return the file and the notifications."""
    notifications = async_mock_service(hass, "persistent_notification", "create")
    await hass.services.async_call(DOMAIN, "get_dashboard_yaml", blocking=True)
    await hass.async_block_till_done()
    text = (Path(hass.config.config_dir) / "givenergy_dashboard.yaml").read_text(encoding="utf-8")
    return text, notifications


def _shown(hass, text: str) -> dict:
    """The dashboard as the frontend would draw it now: hidden sections and cards left out."""
    states = {state.entity_id: state.state for state in hass.states.async_all()}
    return seen(yaml.safe_load(text), states)


def _names(text: str, hass=None) -> list[str]:
    """Section headings and tile names, which is what a person reads on the dashboard.

    With *hass*, only those the frontend would show against its current states.
    """
    config = yaml.safe_load(text) if hass is None else _shown(hass, text)
    cards = all_cards(config["views"])
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
    waiting = referenced - _usable_ids(hass, loaded_entry)
    # Only the cards of the one device this install lacks, hidden until it arrives.
    ev_keys = [k for k, device in keys_needing_devices().items() if device == "EV_CHARGER"]
    assert waiting <= {expected_entity_id(key) for key in ev_keys}


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
    names = _names(text, hass)
    assert "Water temperature" in names
    assert "Against the forecast" in names
    assert "EV charger" not in names
    assert "inverter_temperature" in text


async def test_a_charger_found_after_the_file_was_written_shows_up_with_no_regeneration(
    hass, loaded_entry
):
    """The stored file waits for the EV cards, and shows them when discovery finds a charger."""
    text, _ = await _generate(hass)
    assert "EV charger" not in _names(text, hass)
    assert "EV charger" in _names(text)  # the cards are in the file, hidden

    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    await discover_the_charger(hass, loaded_entry)

    assert "EV charger" in _names(text, hass)  # the same file, not generated again
    registry = er.async_get(hass)
    ev_state = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_ev_charger_state"
    )
    assert ev_state is not None
    assert ev_state in text


async def test_a_charger_that_goes_away_hides_its_cards_again(hass, loaded_entry_with_charger):
    text, _ = await _generate(hass)
    assert "EV charger" in _names(text, hass)

    registry = er.async_get(hass)
    ev_state = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry_with_charger.entry_id}_ev_charger_state"
    )
    registry.async_remove(ev_state)
    await hass.async_block_till_done()

    assert "EV charger" not in _names(text, hass)


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
    from custom_components.givenergy_inverter_manager.dashboard import (
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
    from custom_components.givenergy_inverter_manager.dashboard import (
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


async def test_settings_are_visible_to_the_real_administrators_only(hass, loaded_entry):
    admin = await hass.auth.async_create_user("Admin", group_ids=[GROUP_ID_ADMIN])
    other = await hass.auth.async_create_user("Other admin", group_ids=[GROUP_ID_ADMIN])
    resident = await hass.auth.async_create_user("Resident", group_ids=[GROUP_ID_USER])
    await hass.auth.async_update_user(other, is_active=False)

    views = yaml.safe_load((await _generate(hass))[0])["views"]

    settings = next(v for v in views if v["path"] == "settings")
    assert settings["visible"] == [{"user": admin.id}]
    assert resident.id not in str((await _generate(hass))[0])
    [button] = [
        b
        for card in all_cards(views)
        for b in card.get("badges", [])
        if b["tap_action"]["navigation_path"] == "settings"
    ]
    assert button["visibility"] == [{"condition": "user", "users": [admin.id]}]


async def test_without_an_administrator_there_is_no_settings_view(hass, loaded_entry):
    views = yaml.safe_load((await _generate(hass))[0])["views"]
    assert "settings" not in {v["path"] for v in views}
    assert "navigation_path: settings" not in (await _generate(hass))[0]


async def test_live_dashboard_matches_the_docs_example(hass, loaded_entry_with_charger):
    """Full config, every sensor enabled and an EV charger: the output is the docs example."""
    loaded_entry = loaded_entry_with_charger
    admin = await hass.auth.async_create_user("Admin", group_ids=[GROUP_ID_ADMIN])

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
    await discover_the_charger(hass, loaded_entry)

    text, _ = await _generate(hass)

    example = Path(__file__).parents[2] / "docs" / "dashboard-example.yaml"
    assert text.replace(admin.id, ADMIN_ID) == example.read_text(encoding="utf-8")


# ── the "where today's energy came from" card, rendered by Home Assistant ────


def _sources_card(text: str) -> str:
    """The markdown of the sources card on the Today tab, as the file holds it."""
    today = next(v for v in yaml.safe_load(text)["views"] if v["path"] == "today")
    cards = [
        c for c in view_cards(today) if c["type"] == "markdown" and "house_entity" in c["content"]
    ]
    assert len(cards) == 1
    return cards[0]["content"]


def _set_the_live_day(hass, ids: dict[str, str], attributes: dict) -> None:
    hass.states.async_set(ids["self_sufficiency"], "59.3", attributes)
    hass.states.async_set(ids["house_kwh_today"], "11.3")
    hass.states.async_set(ids["import_today"], "12.1")
    hass.states.async_set(ids["battery_discharge_kwh_today"], "1.8")


def _render(hass, content: str) -> str:
    from homeassistant.helpers.template import Template

    return Template(content, hass).async_render(parse_result=False).strip()


_SPLIT_ATTRIBUTES = {
    "house_load_kwh": 11.3,
    "from_grid_kwh": 4.6,
    "grid_to_battery_kwh": 7.5,
    "from_solar_and_battery_kwh": 6.7,
    "basis": "ac_charge_counter",
}


async def test_the_sources_card_is_in_the_file_and_reads_in_plain_words(hass, loaded_entry):
    """A fresh install has the battery discharge sensor disabled, so solar and battery are one."""
    text, _ = await _generate(hass)
    _set_the_live_day(hass, default_entity_ids(), _SPLIT_ATTRIBUTES)

    assert _render(hass, _sources_card(text)) == (
        "House used **11.3 kWh**: solar and battery 6.7 + grid 4.6.\n\n"
        "Grid import **12.1 kWh**: 4.6 for the house + 7.5 into the battery.\n\n"
        "**Self-sufficiency 59%** is the share of what the house used that did not come from "
        "the grid."
    )


async def test_the_sources_card_splits_solar_and_battery_with_the_discharge_sensor(
    hass, loaded_entry
):
    from custom_components.givenergy_inverter_manager.dashboard.templates import (
        EnergySources,
        energy_sources_template,
    )

    ids = default_entity_ids()
    _set_the_live_day(hass, ids, _SPLIT_ATTRIBUTES)
    sources = EnergySources(
        ids["self_sufficiency"],
        ids["house_kwh_today"],
        ids["import_today"],
        ids["battery_discharge_kwh_today"],
    )
    rendered = _render(hass, energy_sources_template(sources))
    assert rendered.startswith("House used **11.3 kWh**: solar 4.9 + battery 1.8 + grid 4.6.")


async def test_the_sources_card_falls_back_to_the_totals_without_the_attributes(hass, loaded_entry):
    text, _ = await _generate(hass)
    _set_the_live_day(hass, default_entity_ids(), {})
    rendered = _render(hass, _sources_card(text))
    assert rendered.startswith("House used **11.3 kWh**: solar and battery 0.0 + grid 11.3.")
    assert "is not known" in rendered


async def test_the_sources_card_waits_while_the_totals_are_unavailable(hass, loaded_entry):
    text, _ = await _generate(hass)
    ids = default_entity_ids()
    hass.states.async_set(ids["house_kwh_today"], "unavailable")
    hass.states.async_set(ids["self_sufficiency"], "unavailable", {})
    assert _render(hass, _sources_card(text)) == "Waiting for today's energy totals."
