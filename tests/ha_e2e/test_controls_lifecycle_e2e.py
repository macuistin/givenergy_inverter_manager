"""The controls across an upgrade, an empty entry and the immersion switch coming and going."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from controls_support import (
    BRIEF_DEFAULTS,
    CONTROL_KEYS,
    entity_id_of,
    set_control,
    value_of,
)
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import every_field, walk_options_forms

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_SURPLUS_DIVERT_SOC,
    DOMAIN,
)


@pytest.fixture
def scenario():
    return MIDDAY


@pytest.fixture
def bare_entry(config_entry):
    """An install whose entry holds none of the control keys, as if nobody ever saved one."""
    data = {k: v for k, v in config_entry.data.items() if k not in CONTROL_KEYS}
    return MockConfigEntry(
        domain=DOMAIN, title=config_entry.title, data=data, unique_id=config_entry.unique_id
    )


class TestWhenNothingIsSaved:
    async def test_every_control_shows_its_default(self, hass, hass_in_scenario, service_calls, bare_entry):
        bare_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(bare_entry.entry_id)
        await hass.async_block_till_done()
        try:
            assert not any(k in bare_entry.data or k in bare_entry.options for k in CONTROL_KEYS)
            for key, expected in BRIEF_DEFAULTS.items():
                assert value_of(hass, bare_entry, key) == expected, key
            # The engine reads the same defaults, so what the user sees is what runs.
            coordinator = bare_entry.runtime_data
            assert coordinator.is_dry_run is False
        finally:
            await hass.config_entries.async_unload(bare_entry.entry_id)
            await hass.async_block_till_done()

    async def test_setting_up_writes_no_control_option(
        self, hass, hass_in_scenario, service_calls, bare_entry
    ):
        """Nothing is seeded or migrated: a control with nothing saved leaves the entry alone."""
        data = dict(bare_entry.data)
        bare_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(bare_entry.entry_id)
        await hass.async_block_till_done()
        try:
            assert dict(bare_entry.data) == data
            assert not set(bare_entry.options) & set(CONTROL_KEYS)
        finally:
            await hass.config_entries.async_unload(bare_entry.entry_id)
            await hass.async_block_till_done()


class TestTheUpgradeKeepsEveryValue:
    """An install from before the controls holds its values in the setup data and the options.

    The controls read the same keys, so the values it had are the values shown and used. Nothing
    is copied, rewritten or reset on upgrade.
    """

    OLD_DATA = {
        "surplus_divert_soc_pct": 65,
        "surplus_divert_min_power_w": 900,
        "cheap_rate_floor_soc": 40,
        "skip_charge_soc_threshold_pct": 75,
        "forecast_conservatism": 0.35,
    }
    OLD_OPTIONS = {
        "cheap_rate_floor_soc": 30.0,
        "skip_charge_soc_threshold_pct": 85.0,
        "forecast_conservatism": 0.55,
        "dry_run": True,
        "verbose_logging": True,
    }

    @pytest.fixture
    def old_entry(self, config_entry):
        return MockConfigEntry(
            domain=DOMAIN,
            title=config_entry.title,
            data={**config_entry.data, **self.OLD_DATA},
            options=dict(self.OLD_OPTIONS),
            unique_id=config_entry.unique_id,
        )

    @pytest.fixture
    async def upgraded(self, hass, hass_in_scenario, service_calls, old_entry):
        old_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(old_entry.entry_id)
        await hass.async_block_till_done()
        yield old_entry
        if old_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(old_entry.entry_id)
            await hass.async_block_till_done()

    async def test_each_control_shows_the_value_the_install_had(self, hass, upgraded):
        assert value_of(hass, upgraded, "surplus_divert_soc_pct") == 65
        assert value_of(hass, upgraded, "surplus_divert_min_power_w") == 900
        assert value_of(hass, upgraded, "cheap_rate_floor_soc") == 30
        assert value_of(hass, upgraded, "skip_charge_soc_threshold_pct") == 85
        assert value_of(hass, upgraded, "forecast_conservatism") == pytest.approx(0.55)
        assert value_of(hass, upgraded, "dry_run") == "on"
        assert value_of(hass, upgraded, "verbose_logging") == "on"

    async def test_the_engine_runs_on_those_values(self, hass, upgraded):
        cfg = upgraded.runtime_data._effective_cfg()
        assert cfg["surplus_divert_soc_pct"] == 65
        assert cfg["cheap_rate_floor_soc"] == 30.0
        assert upgraded.runtime_data.is_dry_run is True

    async def test_nothing_in_the_entry_moved(self, hass, upgraded):
        # Setup records the tariff review date and picks the GivTCP capacity sensor itself.
        # No control key is added or changed.
        own = {"tariff_reviewed_on", "battery_capacity_entity"}
        saved = {k: v for k, v in upgraded.options.items() if k not in own}
        assert saved == self.OLD_OPTIONS
        for key, value in self.OLD_DATA.items():
            assert upgraded.data[key] == value

    async def test_no_options_page_offers_them(self, hass, upgraded):
        forms = await walk_options_forms(hass, upgraded)
        offered = {field["name"] for form in forms.values() for field in every_field(form["fields"])}
        assert offered
        assert offered.isdisjoint(CONTROL_KEYS)


class TestTheDivertThresholdsFollowTheImmersionSwitch:
    """The two divert controls are about the heater, so they exist while a heater is set."""

    @pytest.fixture
    async def without_a_heater(self, hass, hass_in_scenario, service_calls, config_entry):
        data = {k: v for k, v in config_entry.data.items() if "immersion" not in k}
        entry = MockConfigEntry(
            domain=DOMAIN, title=config_entry.title, data=data, unique_id=config_entry.unique_id
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()

    async def test_without_a_heater_only_the_other_controls_exist(self, hass, without_a_heater):
        absent = {"surplus_divert_soc_pct", "surplus_divert_min_power_w"}
        for key in CONTROL_KEYS:
            assert (entity_id_of(hass, without_a_heater, key) is None) == (key in absent), key

    async def test_adding_a_heater_adds_them_with_the_value_already_saved(
        self, hass, without_a_heater
    ):
        hass.config_entries.async_update_entry(
            without_a_heater,
            options={**without_a_heater.options, CONF_SURPLUS_DIVERT_SOC: 70},
        )
        await hass.async_block_till_done()
        hass.states.async_set("switch.second_heater", "off")

        hass.config_entries.async_update_entry(
            without_a_heater,
            options={**without_a_heater.options, CONF_IMMERSION_SWITCH: "switch.second_heater"},
        )
        await hass.async_block_till_done()

        assert without_a_heater.state is ConfigEntryState.LOADED
        assert value_of(hass, without_a_heater, CONF_SURPLUS_DIVERT_SOC) == 70
        assert value_of(hass, without_a_heater, "surplus_divert_min_power_w") == 500

    async def test_removing_the_heater_removes_them_and_keeps_the_saved_value(
        self, hass, loaded_entry
    ):
        await set_control(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC, 70)
        assert entity_id_of(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC) is not None

        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_IMMERSION_SWITCH: ""}
        )
        await hass.async_block_till_done()

        assert entity_id_of(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC) is None
        assert loaded_entry.options[CONF_SURPLUS_DIVERT_SOC] == 70
