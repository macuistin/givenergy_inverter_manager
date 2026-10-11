"""The test instance marker file, against a real Home Assistant.

A file named .givenergy_test_instance in the configuration folder makes the whole integration
read dry run: the write guard, the snapshot, the dry run sensor, the log, the diagnostics, the
Dry run switch and the dashboard banner. It is read once, at setup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from conftest import (
    CHARGE_END,
    CHARGE_START,
    ENABLE_SCHEDULE,
    ENABLE_TARGET,
    IMMERSION_SWITCH,
    MIDDAY,
    set_givtcp_states,
)
from controls_support import control, entity_id_of
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from test_reload_policy_e2e import OLD_TRIGGER, PRE_WINDOW, _fire_trigger_at

import custom_components.givenergy_inverter_manager.coordinator as coordinator_module
from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    DOMAIN,
    TEST_INSTANCE_MARKER,
)
from custom_components.givenergy_inverter_manager.controls import TEST_INSTANCE_LOCKED
from custom_components.givenergy_inverter_manager.dashboard.render import (
    async_host_facts,
    build_dashboard,
)


@pytest.fixture
def scenario():
    return PRE_WINDOW


def _marker(hass) -> Path:
    return Path(hass.config.config_dir) / TEST_INSTANCE_MARKER


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


@pytest.fixture
async def marked_entry(hass, hass_in_scenario, service_calls, config_entry):
    """An entry set up while the marker file exists. Its saved dry run option is off."""
    _marker(hass).write_text("")
    assert config_entry.data.get(CONF_DRY_RUN) is None
    yield await _setup(hass, config_entry)
    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


class TestWithTheMarker:
    async def test_the_coordinator_and_the_snapshot_both_read_dry_run(self, marked_entry):
        coordinator = marked_entry.runtime_data
        assert marked_entry.options.get(CONF_DRY_RUN) is None
        assert coordinator.test_instance is True
        assert coordinator.is_dry_run is True
        assert coordinator.data.dry_run is True
        assert coordinator.data.test_instance is True

    async def test_the_saved_option_cannot_turn_it_off(self, hass, marked_entry):
        hass.config_entries.async_update_entry(
            marked_entry, options={**marked_entry.options, CONF_DRY_RUN: False}
        )
        await hass.async_block_till_done()

        assert marked_entry.runtime_data.is_dry_run is True

    async def test_the_dry_run_sensor_says_on_and_flags_a_test_instance(self, hass, marked_entry):
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{marked_entry.entry_id}_dry_run_active"
        )

        state = hass.states.get(entity_id)

        assert state.state == "True"
        assert state.attributes["summary"] == "On"
        assert state.attributes["test_instance"] is True

    async def test_the_switch_reads_on_and_cannot_be_turned_off(self, hass, marked_entry):
        switch = control(hass, marked_entry, CONF_DRY_RUN)
        assert hass.states.get(entity_id_of(hass, marked_entry, CONF_DRY_RUN)).state == "on"
        assert (
            hass.states.get(entity_id_of(hass, marked_entry, CONF_DRY_RUN)).attributes[
                "test_instance"
            ]
            is True
        )

        with pytest.raises(ServiceValidationError) as raised:
            await switch.async_turn_off()

        assert raised.value.translation_domain == DOMAIN
        assert raised.value.translation_key == TEST_INSTANCE_LOCKED
        assert TEST_INSTANCE_MARKER in str(raised.value)
        assert hass.states.get(entity_id_of(hass, marked_entry, CONF_DRY_RUN)).state == "on"
        assert CONF_DRY_RUN not in marked_entry.options

    async def test_the_charge_target_is_not_written_at_its_trigger(
        self, hass, marked_entry, monkeypatch
    ):
        """The same trigger writes with no marker (see the control test below)."""
        coordinator = marked_entry.runtime_data
        skipped = []
        real = coordinator._record_skipped
        monkeypatch.setattr(
            coordinator, "_record_skipped", lambda action: skipped.append(action) or real(action)
        )

        assert await _fire_trigger_at(hass, marked_entry, OLD_TRIGGER) == []

        assert any(action.startswith("Would write charge target") for action in skipped), skipped

    async def test_no_switch_or_select_command_reaches_the_inverter_or_the_heater(
        self, hass, marked_entry, service_calls
    ):
        await _fire_trigger_at(hass, marked_entry, OLD_TRIGGER)
        await marked_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        written = {
            call.data["entity_id"]
            for name in ("switch.turn_on", "switch.turn_off", "select.select_option")
            for call in service_calls[name]
        }
        assert written.isdisjoint(
            {ENABLE_TARGET, ENABLE_SCHEDULE, CHARGE_START, CHARGE_END, IMMERSION_SWITCH}
        )

    async def test_the_diagnostics_say_so(self, hass, hass_client, service_calls, config_entry, tmp_path):
        """The clock is not frozen here: aiohttp's access logger fails under a frozen time."""
        hass.config.config_dir = str(tmp_path)
        set_givtcp_states(hass, MIDDAY)
        (tmp_path / TEST_INSTANCE_MARKER).write_text("")
        await _setup(hass, config_entry)

        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

        assert diagnostics["coordinator"]["test_instance"] is True
        assert diagnostics["coordinator"]["dry_run_in_force"] is True
        assert diagnostics["current_data"]["dry_run"] is True
        assert diagnostics["config"].get(CONF_DRY_RUN) is None
        await hass.config_entries.async_unload(config_entry.entry_id)

    async def test_the_log_names_the_file_and_the_way_out(self, hass, hass_in_scenario, service_calls, config_entry, caplog):
        _marker(hass).write_text("")
        with caplog.at_level(logging.WARNING):
            await _setup(hass, config_entry)
        try:
            message = next(r.getMessage() for r in caplog.records if "marker" in r.getMessage())
            assert str(_marker(hass)) in message
            assert "Delete the file" in message
        finally:
            await hass.config_entries.async_unload(config_entry.entry_id)

    async def test_the_dashboard_banner_says_test_instance(self, hass, marked_entry):
        banner = await _banner(hass, marked_entry)
        assert "**Test instance.**" in banner
        assert "Delete the file" in banner
        assert "turns off the Dry run switch" not in banner


class TestWithoutTheMarker:
    @pytest.fixture
    async def plain_entry(self, hass, hass_in_scenario, service_calls, config_entry):
        yield await _setup(hass, config_entry)
        if config_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(config_entry.entry_id)
            await hass.async_block_till_done()

    async def test_the_saved_option_rules(self, hass, plain_entry):
        coordinator = plain_entry.runtime_data
        assert coordinator.test_instance is False
        assert coordinator.is_dry_run is False
        assert coordinator.data.test_instance is False
        await control(hass, plain_entry, CONF_DRY_RUN).async_turn_on()
        assert coordinator.is_dry_run is True
        await control(hass, plain_entry, CONF_DRY_RUN).async_turn_off()
        assert coordinator.is_dry_run is False

    async def test_the_charge_target_is_written_at_its_trigger(self, hass, plain_entry):
        """The control for the marker test: with no marker the same trigger writes."""
        assert await _fire_trigger_at(hass, plain_entry, OLD_TRIGGER) != []

    async def test_the_sensor_carries_no_test_instance_flag(self, hass, plain_entry):
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{plain_entry.entry_id}_dry_run_active"
        )
        assert "test_instance" not in hass.states.get(entity_id).attributes

    async def test_the_dashboard_banner_points_at_the_switch(self, hass, plain_entry):
        banner = await _banner(hass, plain_entry)
        assert "**Test instance.**" not in banner
        assert "turns off the Dry run switch in Settings" in banner


class TestTheMarkerIsReadOnce:
    async def test_it_is_looked_for_at_setup_and_never_again(
        self, hass, hass_in_scenario, service_calls, config_entry, monkeypatch
    ):
        looked = []
        real = os.path.exists
        monkeypatch.setattr(
            coordinator_module.os.path,
            "exists",
            lambda path: looked.append(path) or real(path),
        )
        await _setup(hass, config_entry)
        try:
            at_setup = [p for p in looked if p.endswith(TEST_INSTANCE_MARKER)]
            assert len(at_setup) == 1
            for _ in range(3):
                await config_entry.runtime_data.async_refresh()
            assert [p for p in looked if p.endswith(TEST_INSTANCE_MARKER)] == at_setup
        finally:
            await hass.config_entries.async_unload(config_entry.entry_id)

    async def test_a_file_created_after_setup_is_not_noticed_until_the_next_setup(
        self, hass, hass_in_scenario, service_calls, config_entry
    ):
        await _setup(hass, config_entry)
        try:
            _marker(hass).write_text("")
            await config_entry.runtime_data.async_refresh()
            assert config_entry.runtime_data.is_dry_run is False

            assert await hass.config_entries.async_reload(config_entry.entry_id)
            await hass.async_block_till_done()
            assert config_entry.runtime_data.is_dry_run is True
        finally:
            await hass.config_entries.async_unload(config_entry.entry_id)

    async def test_a_file_removed_after_setup_keeps_dry_run_until_the_next_setup(
        self, hass, marked_entry
    ):
        _marker(hass).unlink()
        await marked_entry.runtime_data.async_refresh()
        assert marked_entry.runtime_data.is_dry_run is True

        assert await hass.config_entries.async_reload(marked_entry.entry_id)
        await hass.async_block_till_done()
        assert marked_entry.runtime_data.is_dry_run is False
        assert marked_entry.runtime_data.data.dry_run is False


async def _banner(hass, entry) -> str:
    """The dry run banner's markdown, rendered by Home Assistant's template engine."""
    dashboard = build_dashboard(hass, entry, await async_host_facts(hass, is_admin=True))
    cards = [
        card
        for view in dashboard["views"]
        for section in view["sections"]
        for card in section["cards"]
        if card["type"] == "markdown" and "No commands are sent" in card["content"]
    ]
    assert len(cards) == 1
    return Template(cards[0]["content"], hass).async_render()
