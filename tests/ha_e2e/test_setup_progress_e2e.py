"""The setup checklist and the dry run banner against a real Home Assistant.

The Setup Progress sensor works out the checklist each cycle from the saved config and the
readings. The dashboard card reads its `items` attribute and the frontend shows it while the
state is incomplete. These tests change the install step by step, watch the checklist tick, and
render the cards with Home Assistant's own templates.
"""

from __future__ import annotations

from pathlib import Path

from conftest import FORECAST, ZAPPI_STATES, discover_the_charger
from controls_support import control
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template

from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_FORECAST_ENTITY,
    CONF_IMMERSION_SWITCH,
    CONF_RATE_PERIODS,
    DOMAIN,
    TEST_INSTANCE_MARKER,
)
from custom_components.givenergy_inverter_manager.strategy import async_dashboard_for_websocket
from tests.dashboard_visibility import seen

REQUIRED = ("inverter", "tariff", "cheap_window", "forecast", "dry_run")


def _entity(hass, entry, key: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


def _progress(hass, entry):
    return hass.states.get(_entity(hass, entry, "setup_progress"))


def _done(hass, entry) -> dict[str, bool]:
    return {item["key"]: item["done"] for item in _progress(hass, entry).attributes["items"]}


async def _refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def _headings_shown(hass) -> list[str]:
    dashboard = await async_dashboard_for_websocket(hass, is_admin=True)
    states = {state.entity_id: state.state for state in hass.states.async_all()}
    power_flow = next(v for v in seen(dashboard, states)["views"] if v["path"] == "power-flow")
    return [s["cards"][0].get("heading") for s in power_flow["sections"]]


async def _card_text(hass, heading: str) -> str:
    dashboard = await async_dashboard_for_websocket(hass, is_admin=True)
    power_flow = next(v for v in dashboard["views"] if v["path"] == "power-flow")
    section = next(s for s in power_flow["sections"] if s["cards"][0].get("heading") == heading)
    markdown = next(c for c in section["cards"] if c["type"] == "markdown")
    return Template(markdown["content"], hass).async_render().strip()


class TestTheSensor:
    async def test_a_full_install_is_complete(self, hass, loaded_entry):
        state = _progress(hass, loaded_entry)
        assert state.state == "complete"
        assert [i["key"] for i in state.attributes["items"]][:5] == list(REQUIRED)
        assert all(_done(hass, loaded_entry)[key] for key in REQUIRED)

    async def test_the_optional_items_follow_the_install(self, hass, loaded_entry):
        done = _done(hass, loaded_entry)
        assert done["hot_water"] is True  # the full config has an immersion switch
        assert done["ev_charger"] is False  # no charger has been discovered

    async def test_it_is_a_diagnostic_sensor_the_user_can_see_and_use(self, hass, loaded_entry):
        entry = er.async_get(hass).async_get(_entity(hass, loaded_entry, "setup_progress"))
        assert entry.disabled_by is None
        assert entry.entity_category.value == "diagnostic"


class TestItemsTick:
    async def test_dry_run_on_makes_it_incomplete_and_off_completes_it(self, hass, loaded_entry):
        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_on()
        await _refresh(hass, loaded_entry)
        assert _progress(hass, loaded_entry).state == "incomplete"
        assert _done(hass, loaded_entry)["dry_run"] is False

        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_off()
        await _refresh(hass, loaded_entry)
        assert _progress(hass, loaded_entry).state == "complete"
        assert _done(hass, loaded_entry)["dry_run"] is True

    async def test_a_forecast_that_cannot_be_read_is_not_done(self, hass, loaded_entry):
        hass.states.async_set(FORECAST, "unavailable")
        await _refresh(hass, loaded_entry)

        assert _done(hass, loaded_entry)["forecast"] is False
        assert _progress(hass, loaded_entry).state == "incomplete"

        hass.states.async_set(FORECAST, 14.2, {"unit_of_measurement": "kWh"})
        await _refresh(hass, loaded_entry)
        assert _done(hass, loaded_entry)["forecast"] is True

    async def test_removing_the_forecast_entity_from_the_options_is_not_done(
        self, hass, loaded_entry
    ):
        data = {k: v for k, v in loaded_entry.data.items() if k != CONF_FORECAST_ENTITY}
        hass.config_entries.async_update_entry(loaded_entry, data=data)
        await hass.async_block_till_done()
        await _refresh(hass, loaded_entry)

        assert loaded_entry.state is ConfigEntryState.LOADED
        assert _done(hass, loaded_entry)["forecast"] is False

    async def test_no_timed_rate_means_no_cheap_window(self, hass, loaded_entry):
        data = {**loaded_entry.data, CONF_RATE_PERIODS: []}
        hass.config_entries.async_update_entry(loaded_entry, data=data)
        await hass.async_block_till_done()
        await _refresh(hass, loaded_entry)

        assert _done(hass, loaded_entry)["cheap_window"] is False
        assert _progress(hass, loaded_entry).state == "incomplete"

    async def test_an_unavailable_inverter_reading_is_not_found(self, hass, loaded_entry):
        from conftest import SOC

        hass.states.async_set(SOC, "unavailable")
        await _refresh(hass, loaded_entry)

        assert _done(hass, loaded_entry)["inverter"] is False

    async def test_a_discovered_charger_ticks_the_optional_item_and_never_holds_it_open(
        self, hass, loaded_entry
    ):
        for entity_id, state in ZAPPI_STATES.items():
            hass.states.async_set(entity_id, state)
        await discover_the_charger(hass, loaded_entry)

        assert _done(hass, loaded_entry)["ev_charger"] is True
        assert _progress(hass, loaded_entry).state == "complete"

    async def test_hot_water_follows_the_immersion_switch_option(self, hass, loaded_entry):
        data = {k: v for k, v in loaded_entry.data.items() if k != CONF_IMMERSION_SWITCH}
        hass.config_entries.async_update_entry(loaded_entry, data=data)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(loaded_entry.entry_id)
        await hass.async_block_till_done()

        assert _done(hass, loaded_entry)["hot_water"] is False
        assert _progress(hass, loaded_entry).state == "complete"


class TestOnATestInstance:
    async def test_dry_run_off_is_not_required_so_the_checklist_can_finish(
        self, hass, hass_in_scenario, service_calls, config_entry
    ):
        Path(hass.config.config_dir, TEST_INSTANCE_MARKER).write_text("")
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        items = {i["key"]: i for i in _progress(hass, config_entry).attributes["items"]}
        assert items["dry_run"]["done"] is False
        assert items["dry_run"]["required"] is False
        assert _progress(hass, config_entry).state == "complete"


class TestTheDashboardCards:
    async def test_the_checklist_shows_while_incomplete_and_hides_when_done(
        self, hass, loaded_entry
    ):
        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_on()
        await _refresh(hass, loaded_entry)
        assert "Finish setting up" in await _headings_shown(hass)

        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_off()
        await _refresh(hass, loaded_entry)
        assert "Finish setting up" not in await _headings_shown(hass)

    async def test_the_card_text_ticks_with_the_items(self, hass, loaded_entry):
        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_on()
        await _refresh(hass, loaded_entry)

        text = await _card_text(hass, "Finish setting up")

        assert "- To do: Dry run turned off" in text
        assert "- Done: Tariff set" in text
        assert "Available: EV charger" in text
        assert "Hot water" not in text

    async def test_the_checklist_text_is_empty_of_required_lines_once_done(
        self, hass, loaded_entry
    ):
        text = await _card_text(hass, "Finish setting up")
        assert "To do" not in text

    async def test_the_banner_text_matches_the_dry_run_sensors(self, hass, loaded_entry):
        await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_on()
        await _refresh(hass, loaded_entry)
        skipped = hass.states.get(_entity(hass, loaded_entry, "dry_run_last_skipped"))
        plan = hass.states.get(_entity(hass, loaded_entry, "charge_plan"))
        assert skipped.state.startswith("Would ")

        text = await _card_text(hass, "Dry run is on")

        assert f"**Last skipped action:** {skipped.state}" in text
        assert f"**Tonight's charge plan:** {plan.state}" in text
        assert "Dry run is on" in await _headings_shown(hass)
