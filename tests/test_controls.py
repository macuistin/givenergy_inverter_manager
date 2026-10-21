"""The tuning controls: their table, the value they show and what a write touches.

The real Home Assistant behaviour (registration, restore, no reload, the options form) is in
tests/ha_e2e/test_controls_e2e.py. These pin the table against the design brief, and the
entity logic against doubles.
"""

from __future__ import annotations

import asyncio
from types import MappingProxyType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager import controls
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.core.reload_policy import Effect, change_effect

# The table of section 5 of the design brief: key, default, low, high, step. It is written out
# here, not read from controls.py, so a range that drifts fails.
BRIEF_NUMBERS = {
    "surplus_divert_soc_pct": (80, 50, 100, 5),
    "surplus_divert_min_power_w": (500, 100, 2000, 100),
    "cheap_rate_floor_soc": (40, 0, 80, 5),
    "skip_charge_soc_threshold_pct": (75, 20, 100, 1),
    "forecast_conservatism": (0.35, 0.0, 1.0, 0.05),
}
BRIEF_SWITCHES = ("dry_run", "verbose_logging", "charge_replan")


class FakeEntries:
    """Records async_update_entry calls and applies them, like the config entries manager."""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    def async_update_entry(self, entry, *, options):
        self.updates.append(dict(options))
        entry.options = MappingProxyType(dict(options))


def _entry(data=None, options=None):
    return SimpleNamespace(
        entry_id="entry",
        data=MappingProxyType(dict(data or {})),
        options=MappingProxyType(dict(options or {})),
    )


def _coordinator(data=None, options=None, test_instance=False, dry_run=False):
    return SimpleNamespace(
        entry=_entry(data, options),
        test_instance=test_instance,
        is_dry_run=dry_run,
        hass=MagicMock(),
    )


def _number(key, **entry_values):
    coordinator = _coordinator(**entry_values)
    spec = next(s for s in controls.NUMBER_SPECS if s.key == key)
    entity = controls.ControlNumber(coordinator, spec)
    entity.hass = SimpleNamespace(config_entries=FakeEntries())
    return entity


class TestTheTableMatchesTheBrief:
    def test_every_number_has_the_brief_range_step_and_default(self):
        actual = {s.key: (s.default, s.low, s.high, s.step) for s in controls.NUMBER_SPECS}
        assert actual == BRIEF_NUMBERS

    def test_the_switches_are_dry_run_verbose_logging_and_replan(self):
        coordinator = _coordinator()
        assert [s._option_key for s in controls.control_switches(coordinator)] == list(
            BRIEF_SWITCHES
        )

    def test_the_unique_id_is_the_entry_id_and_the_option_key(self):
        coordinator = _coordinator()
        everything = [
            *controls.control_switches(coordinator),
            *controls.control_numbers(coordinator),
            *controls.control_numbers(coordinator, Device.IMMERSION_SWITCH),
        ]
        assert sorted(e._attr_unique_id for e in everything) == sorted(
            f"entry_{key}" for key in (*BRIEF_SWITCHES, *BRIEF_NUMBERS)
        )

    def test_the_translation_key_is_the_option_key(self):
        coordinator = _coordinator()
        for entity in controls.control_switches(coordinator):
            assert entity._attr_translation_key == entity._option_key

    def test_only_the_two_divert_thresholds_need_the_immersion_switch(self):
        always = {s.key for s in controls.NUMBER_SPECS if s.requires is None}
        divert = {s.key for s in controls.NUMBER_SPECS if s.requires is Device.IMMERSION_SWITCH}
        assert divert == {"surplus_divert_soc_pct", "surplus_divert_min_power_w"}
        assert always == set(BRIEF_NUMBERS) - divert

    def test_the_numbers_a_device_does_not_need_are_built_without_one(self):
        keys = {e._option_key for e in controls.control_numbers(_coordinator())}
        assert keys == {
            "cheap_rate_floor_soc",
            "skip_charge_soc_threshold_pct",
            "forecast_conservatism",
        }

    def test_every_control_is_a_live_key_so_a_write_never_reloads(self):
        for key in (*BRIEF_SWITCHES, *BRIEF_NUMBERS):
            assert change_effect({key: 1}, {key: 2}) is Effect.LIVE, key


class TestTheValueShown:
    @pytest.mark.parametrize("key", list(BRIEF_NUMBERS))
    def test_a_missing_option_shows_the_default(self, key):
        assert _number(key).native_value == BRIEF_NUMBERS[key][0]

    def test_an_old_setup_value_is_shown_and_keeps_its_value(self):
        """An install that set the threshold at setup keeps it: the control reads setup data."""
        assert _number("surplus_divert_soc_pct", data={"surplus_divert_soc_pct": 65}).native_value == 65

    def test_a_saved_option_wins_over_the_setup_value(self):
        entity = _number(
            "cheap_rate_floor_soc",
            data={"cheap_rate_floor_soc": 40},
            options={"cheap_rate_floor_soc": 25},
        )
        assert entity.native_value == 25

    def test_a_saved_zero_is_a_real_choice_not_a_missing_value(self):
        entity = _number("cheap_rate_floor_soc", options={"cheap_rate_floor_soc": 0})
        assert entity.native_value == 0

    def test_a_value_that_is_not_a_number_falls_back_to_the_default(self):
        entity = _number("forecast_conservatism", options={"forecast_conservatism": "high"})
        assert entity.native_value == 0.35


class TestWritingAControl:
    def test_a_number_saves_its_own_key_and_keeps_every_other_option(self):
        entity = _number("cheap_rate_floor_soc", options={"base_rate": 0.3, "dry_run": True})

        asyncio.run(entity.async_set_native_value(55))

        assert entity.hass.config_entries.updates == [
            {"base_rate": 0.3, "dry_run": True, "cheap_rate_floor_soc": 55}
        ]

    def test_the_write_reads_the_options_as_they_are_now(self):
        """Another control saves between two writes. A copy taken earlier would undo it."""
        first = _number("cheap_rate_floor_soc")
        second = controls.ControlNumber(
            first.coordinator, next(s for s in controls.NUMBER_SPECS if s.key == "forecast_conservatism")
        )
        second.hass = first.hass

        asyncio.run(first.async_set_native_value(55))
        asyncio.run(second.async_set_native_value(0.5))

        assert first.hass.config_entries.updates[-1] == {
            "cheap_rate_floor_soc": 55,
            "forecast_conservatism": 0.5,
        }

    def test_a_whole_number_control_saves_an_int(self):
        entity = _number("surplus_divert_min_power_w")
        asyncio.run(entity.async_set_native_value(700.0))
        saved = entity.hass.config_entries.updates[-1]["surplus_divert_min_power_w"]
        assert saved == 700
        assert isinstance(saved, int)

    def test_conservatism_is_rounded_to_the_step(self):
        entity = _number("forecast_conservatism")
        asyncio.run(entity.async_set_native_value(0.30000000000000004))
        assert entity.hass.config_entries.updates[-1]["forecast_conservatism"] == 0.3

    def test_a_switch_saves_its_flag(self):
        coordinator = _coordinator(options={"base_rate": 0.3})
        entity = controls.control_switches(coordinator)[1]
        entity.hass = SimpleNamespace(config_entries=FakeEntries())

        asyncio.run(entity.async_turn_on())

        assert entity.hass.config_entries.updates == [{"base_rate": 0.3, "verbose_logging": True}]
        assert entity.is_on is True
        asyncio.run(entity.async_turn_off())
        assert entity.is_on is False


class TestTheDryRunSwitch:
    def _switch(self, **kwargs):
        entity = controls.DryRunSwitch(_coordinator(**kwargs))
        entity.hass = SimpleNamespace(config_entries=FakeEntries())
        return entity

    def test_it_shows_what_the_coordinator_says_not_the_saved_option(self):
        """A test instance forces dry run, so the switch reads on while the option is off."""
        entity = self._switch(options={"dry_run": False}, dry_run=True, test_instance=True)
        assert entity.is_on is True

    def test_turning_it_off_on_a_test_instance_raises_the_translated_error(self):
        entity = self._switch(dry_run=True, test_instance=True)
        with pytest.raises(controls.ServiceValidationError) as raised:
            asyncio.run(entity.async_turn_off())
        assert raised.value.translation_domain == DOMAIN
        assert raised.value.translation_key == controls.TEST_INSTANCE_LOCKED
        assert entity.hass.config_entries.updates == []

    def test_turning_it_off_elsewhere_saves_the_option(self):
        entity = self._switch(options={"dry_run": True}, dry_run=True)
        asyncio.run(entity.async_turn_off())
        assert entity.hass.config_entries.updates == [{"dry_run": False}]

    def test_a_test_instance_is_flagged_in_the_attributes_and_no_other_is(self):
        assert self._switch(test_instance=True).extra_state_attributes == {"test_instance": True}
        assert self._switch().extra_state_attributes is None
