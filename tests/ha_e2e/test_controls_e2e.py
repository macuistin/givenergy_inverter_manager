"""The tuning controls against a real Home Assistant.

What each control is (its entity, name, icon and category), the value it shows when the option
is absent, saved at setup or saved by the options, that a write keeps every other option and
never reloads, and that the engine uses the new value on the next cycle.
"""

from __future__ import annotations

import pytest
from conftest import IMMERSION_TEMP, MIDDAY, Scenario
from controls_support import (
    BRIEF_DEFAULTS,
    CONTROL_KEYS,
    SWITCH_KEYS,
    control,
    domain_of,
    entity_id_of,
    set_control,
    state_of,
    value_of,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.icon import async_get_icons
from wizard_support import open_options, submit

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_DRY_RUN,
    CONF_FORECAST_CONSERVATISM,
    CONF_IMMERSION_MIN_TEMP,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CONF_VERBOSE_LOGGING,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.logging import get_logger


@pytest.fixture
def scenario():
    return MIDDAY


class TestWhatEachControlIs:
    @pytest.mark.parametrize("key", CONTROL_KEYS)
    async def test_it_is_a_config_entity_with_the_brief_unique_id(self, hass, loaded_entry, key):
        registry = er.async_get(hass)
        entity_id = entity_id_of(hass, loaded_entry, key)
        assert entity_id is not None
        entry = registry.async_get(entity_id)
        assert entry.unique_id == f"{loaded_entry.entry_id}_{key}"
        assert entry.entity_category is EntityCategory.CONFIG
        assert entry.translation_key == key
        assert entry.domain == domain_of(key)

    async def test_the_icons_are_the_ones_the_brief_names(self, hass, loaded_entry):
        brief = {
            "dry_run": "mdi:test-tube",
            "verbose_logging": "mdi:text-box-search-outline",
            "charge_replan": "mdi:battery-sync-outline",
            "surplus_divert_soc_pct": "mdi:battery-charging-high",
            "surplus_divert_min_power_w": "mdi:solar-power",
            "cheap_rate_floor_soc": "mdi:battery-arrow-down-outline",
            "skip_charge_soc_threshold_pct": "mdi:battery-check-outline",
            "forecast_conservatism": "mdi:cloud-percent-outline",
        }
        icons = (await async_get_icons(hass, "entity", [DOMAIN]))[DOMAIN]
        for key, icon in brief.items():
            assert icons[domain_of(key)][key]["default"] == icon, key

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("surplus_divert_soc_pct", (50, 100, 5, "%", None, "slider")),
            ("surplus_divert_min_power_w", (100, 2000, 100, "W", "power", "slider")),
            ("cheap_rate_floor_soc", (0, 80, 5, "%", None, "slider")),
            ("skip_charge_soc_threshold_pct", (20, 100, 1, "%", None, "box")),
            ("forecast_conservatism", (0.0, 1.0, 0.05, None, None, "box")),
        ],
    )
    async def test_each_number_has_the_brief_range_unit_and_mode(
        self, hass, loaded_entry, key, expected
    ):
        attrs = state_of(hass, loaded_entry, key).attributes
        assert (
            attrs["min"],
            attrs["max"],
            attrs["step"],
            attrs.get("unit_of_measurement"),
            attrs.get("device_class"),
            attrs["mode"],
        ) == expected


class TestTheValueShown:
    async def test_values_saved_at_setup_are_shown(self, hass, loaded_entry):
        """The setup data of the shared entry holds the defaults, so the controls show them."""
        for key, expected in BRIEF_DEFAULTS.items():
            assert value_of(hass, loaded_entry, key) == expected, key

    async def test_a_saved_option_is_shown_over_the_setup_value(self, hass, loaded_entry):
        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_CHEAP_RATE_FLOOR_SOC: 25}
        )
        await hass.async_block_till_done()
        assert value_of(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC) == 25

    async def test_a_saved_zero_is_shown_as_zero(self, hass, loaded_entry):
        await set_control(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC, 0)
        assert loaded_entry.options[CONF_CHEAP_RATE_FLOOR_SOC] == 0
        assert value_of(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC) == 0

    async def test_a_value_saved_by_the_options_shows_on_the_next_refresh(self, hass, loaded_entry):
        """A change made anywhere shows. Nothing here asks the entity to refresh itself."""
        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_FORECAST_CONSERVATISM: 0.8}
        )
        await hass.async_block_till_done()
        await loaded_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert value_of(hass, loaded_entry, CONF_FORECAST_CONSERVATISM) == pytest.approx(0.8)

    async def test_a_value_survives_a_reload(self, hass, loaded_entry):
        await set_control(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC, 65)
        await set_control(hass, loaded_entry, CONF_VERBOSE_LOGGING, True)

        assert await hass.config_entries.async_reload(loaded_entry.entry_id)
        await hass.async_block_till_done()

        assert value_of(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC) == 65
        assert value_of(hass, loaded_entry, CONF_VERBOSE_LOGGING) == "on"


class TestWritingAControl:
    async def test_a_write_saves_the_flat_option_and_keeps_the_others(self, hass, loaded_entry):
        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_BASE_RATE: 0.41}
        )
        before = dict(loaded_entry.options)

        await set_control(hass, loaded_entry, CONF_FORECAST_CONSERVATISM, 0.6)

        assert dict(loaded_entry.options) == {**before, CONF_FORECAST_CONSERVATISM: 0.6}

    async def test_a_write_after_a_change_elsewhere_does_not_undo_it(self, hass, loaded_entry):
        """The two writes use the entry's options as they are when each one runs."""
        await set_control(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC, 20)
        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_BASE_RATE: 0.52}
        )
        await set_control(hass, loaded_entry, CONF_SKIP_CHARGE_SOC_THRESHOLD, 90)

        assert loaded_entry.options[CONF_CHEAP_RATE_FLOOR_SOC] == 20
        assert loaded_entry.options[CONF_BASE_RATE] == 0.52
        assert loaded_entry.options[CONF_SKIP_CHARGE_SOC_THRESHOLD] == 90

    async def test_saving_an_options_page_does_not_undo_a_control_changed_meanwhile(
        self, hass, loaded_entry
    ):
        """The page is opened, a control is moved, then the page is saved."""
        result = await open_options(hass, loaded_entry, {"charge_planning": {}})
        assert result["step_id"] == "charge_planning"
        await set_control(hass, loaded_entry, CONF_DRY_RUN, True)
        await set_control(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC, 10)

        result = await submit(hass.config_entries.options, result, overnight_charge_target_pct=90)
        await submit(hass.config_entries.options, result)  # the solar forecast screen
        await hass.async_block_till_done()

        assert loaded_entry.options["overnight_charge_target_pct"] == 90
        assert loaded_entry.options[CONF_DRY_RUN] is True
        assert loaded_entry.options[CONF_CHEAP_RATE_FLOOR_SOC] == 10
        assert value_of(hass, loaded_entry, CONF_DRY_RUN) == "on"

    async def test_a_control_key_sent_to_a_page_is_not_accepted(self, hass, loaded_entry):
        result = await open_options(hass, loaded_entry, {"charge_planning": {}})
        from homeassistant.data_entry_flow import InvalidData

        with pytest.raises(InvalidData):
            await submit(hass.config_entries.options, result, **{CONF_DRY_RUN: True})

    async def test_the_entity_shows_the_new_value_at_once(self, hass, loaded_entry):
        await control(hass, loaded_entry, CONF_FORECAST_CONSERVATISM).async_set_native_value(0.9)
        assert value_of(hass, loaded_entry, CONF_FORECAST_CONSERVATISM) == pytest.approx(0.9)

    async def test_a_write_does_not_reload_the_entry(self, hass, loaded_entry):
        coordinator = loaded_entry.runtime_data
        for key in CONTROL_KEYS:
            await set_control(hass, loaded_entry, key, True if key in SWITCH_KEYS else 55)
            assert loaded_entry.state is ConfigEntryState.LOADED, key
            assert loaded_entry.runtime_data is coordinator, key


@pytest.fixture
async def warm_water(hass, loaded_entry):
    """Water between its minimum and its restart point, so the surplus rules decide the heater."""
    hass.config_entries.async_update_entry(
        loaded_entry, data={**loaded_entry.data, CONF_IMMERSION_MIN_TEMP: 40}
    )
    await hass.async_block_till_done()
    hass.states.async_set(
        IMMERSION_TEMP, 48, {"unit_of_measurement": "°C", "device_class": "temperature"}
    )


class TestTheEngineUsesTheNewValue:
    """Midday in June: battery 62%, 400 W spare solar, water at 48 degrees."""

    async def test_the_divert_thresholds_decide_whether_surplus_goes_to_the_heater(
        self, hass, loaded_entry, warm_water
    ):
        coordinator = loaded_entry.runtime_data
        await coordinator.async_refresh()
        assert coordinator.data.should_divert_immersion is False
        assert "below threshold 80%" in coordinator.data.divert_reason

        await set_control(hass, loaded_entry, CONF_SURPLUS_DIVERT_SOC, 50)
        await coordinator.async_refresh()
        assert coordinator.data.should_divert_immersion is False
        assert "needs 500 W" in coordinator.data.divert_reason

        await set_control(hass, loaded_entry, CONF_SURPLUS_DIVERT_MIN_W, 300)
        await coordinator.async_refresh()
        assert coordinator.data.should_divert_immersion is True

    async def test_the_skip_charge_threshold_changes_the_plan_on_the_next_cycle(
        self, hass, loaded_entry
    ):
        coordinator = loaded_entry.runtime_data
        await coordinator.async_refresh()
        assert "Not skipping" not in coordinator.data.charge_decision.reason

        await set_control(hass, loaded_entry, CONF_SKIP_CHARGE_SOC_THRESHOLD, 50)
        await coordinator.async_refresh()

        assert "Not skipping" in coordinator.data.charge_decision.reason

    async def test_conservatism_changes_the_forecast_the_plan_leans_on(self, hass, loaded_entry):
        """0 plans on the plain forecast (14.2 kWh) and 1 on the pessimistic one (9.8 kWh)."""
        coordinator = loaded_entry.runtime_data
        forecasts = {}
        for value in (0.0, 1.0):
            await set_control(hass, loaded_entry, CONF_FORECAST_CONSERVATISM, value)
            await coordinator.async_refresh()
            forecasts[value] = coordinator.data.charge_decision.forecast_kwh

        assert forecasts == {0.0: 14.2, 1.0: 9.8}

    async def test_verbose_logging_follows_the_switch(self, hass, loaded_entry):
        log = get_logger("givenergy_inverter_manager.test")
        assert log.is_verbose() is False

        await set_control(hass, loaded_entry, CONF_VERBOSE_LOGGING, True)
        assert log.is_verbose() is True

        await set_control(hass, loaded_entry, CONF_VERBOSE_LOGGING, False)
        assert log.is_verbose() is False


# 02:30 on a June night in Dublin, inside the cheapest window, battery at 31%.
SUMMER_NIGHT = Scenario(
    name="summer_cheap_night",
    frozen_utc="2026-06-15 01:30:00+00:00",
    solar_w=0.0,
    battery_soc=31.0,
    battery_w=0.0,
    grid_w=-600.0,
    load_w=600.0,
)


@pytest.mark.parametrize("scenario", [SUMMER_NIGHT])
async def test_the_cheap_rate_floor_is_read_on_the_next_cycle(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    assert "topping up to 40%" in coordinator.data.cheap_rate_floor_status

    await set_control(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC, 60)
    await coordinator.async_refresh()
    assert "floor 60%" in coordinator.data.cheap_rate_floor_status

    await set_control(hass, loaded_entry, CONF_CHEAP_RATE_FLOOR_SOC, 0)
    await coordinator.async_refresh()
    assert coordinator.data.cheap_rate_floor_status == ""


async def test_the_dry_run_switch_is_not_exposed_to_assist(hass, loaded_entry):
    """It has an entity category, which Home Assistant leaves out of Assist by default."""
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    dry_run = entity_id_of(hass, loaded_entry, CONF_DRY_RUN)
    assert async_should_expose(hass, "conversation", dry_run) is False
