"""Setup with the old oil price keys, and with the new alternative heating keys.

The old keys are converted once, in async_setup_entry, with no version bump. The live install
saved an oil price of 1.37 a litre: its advice has to read the same afterwards, word for word.
The reference values below were read from the 0.17 code (the commit this work started from),
run in this harness with the same options and the same two scenarios.
"""

from __future__ import annotations

import pytest
from conftest import CHEAP_NIGHT, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN

KEY = "water_heating_cheapest_source"
OLD_KEYS = {"oil_price_per_litre", "oil_price_entity"}

# What 0.17 published for an install with oil_price_per_litre 1.37, attribute names as they were.
OLD_MIDDAY = {
    "state": "oil",
    "suggestion": (
        "Water is at 48.2°C, close to the 50°C minimum. Oil is cheaper than the grid now "
        "(€0.16 against €0.34 per kWh of heat): run the oil water heating for about 55 minutes "
        "to avoid an electric top-up."
    ),
    "oil_keep_warm": (
        "Water is at 48.2°C, close to the 50°C minimum. Oil is cheaper than the grid now "
        "(€0.16 against €0.34 per kWh of heat): run the oil water heating for about 55 minutes "
        "to avoid an electric top-up."
    ),
    "oil_cost_per_kwh": 0.1557,
    "oil_saving_per_kwh": 0.1877,
    "best_hours_for_oil": ["13:00 to 02:00", "04:00 to 13:00"],
    "electricity_cost_per_kwh": 0.3434,
    "cheapest_electricity_cost_per_kwh": 0.0994,
    "cheapest_source_in_horizon": "electricity",
    "horizon": "next_24_hours",
    "horizon_ends": "13:00",
}
OLD_NIGHT = {
    "state": "electricity",
    "suggestion": (
        "Electricity is the cheapest source now. Oil is cheaper than electricity from 04:00 to "
        "02:00 (saves up to €0.19 per kWh of heat)."
    ),
    "oil_cost_per_kwh": 0.1557,
    "oil_saving_per_kwh": -0.0563,
    "best_hours_for_oil": ["04:00 to 02:00"],
    "electricity_cost_per_kwh": 0.0994,
    "cheapest_electricity_cost_per_kwh": 0.0994,
    "cheapest_source_in_horizon": "electricity",
    "horizon": "next_24_hours",
    "horizon_ends": "02:30",
}
# The attributes that were renamed, and the state value that was.
RENAMED = {
    "oil_cost_per_kwh": "alt_cost_per_kwh",
    "oil_saving_per_kwh": "alt_saving_per_kwh",
    "best_hours_for_oil": "best_hours_for_alt",
    "oil_keep_warm": "alt_keep_warm",
}


def _entry(options: dict | None = None, data: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data or full_config_data(),
        options=options or {},
        unique_id=SERIAL,
        version=1,
    )


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def sensor(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{KEY}")
    return None if entity_id is None else hass.states.get(entity_id)


@pytest.fixture
def reloads(monkeypatch):
    """Count the reloads the update listener asks for."""
    import custom_components.givenergy_inverter_manager as integration

    calls = []
    real = integration.async_reload_entry

    async def _spy(hass, entry):
        calls.append(entry.entry_id)
        await real(hass, entry)

    monkeypatch.setattr(integration, "async_reload_entry", _spy)
    return calls


@pytest.fixture
def conversions(monkeypatch):
    """What the setup conversion decided each time it ran: the result, None for nothing to do."""
    import custom_components.givenergy_inverter_manager as integration

    results = []
    real = integration.converted_alt_heat

    def _spy(data, options):
        result = real(data, options)
        results.append(result)
        return result

    monkeypatch.setattr(integration, "converted_alt_heat", _spy)
    return results


class TestSetupWithTheOldKeys:
    @pytest.fixture
    def scenario(self):
        return MIDDAY

    async def test_the_price_is_converted_and_carried_over_exactly(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        assert entry.options["alt_heat_cost"] == 1.37
        assert entry.options["alt_heat_enabled"] is True
        assert entry.options["alt_heat_label"] == "Oil"
        assert entry.options["alt_heat_cost_unit"] == "litre"

    async def test_the_old_keys_are_gone_from_the_entry(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37, "oil_price_entity": "sensor.oil"})
        await set_up(hass, entry)
        assert OLD_KEYS.isdisjoint(entry.options)
        assert OLD_KEYS.isdisjoint(entry.data)

    async def test_the_other_options_survive(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37, "vat_rate": 13.5, "dry_run": True})
        await set_up(hass, entry)
        assert entry.options["vat_rate"] == 13.5
        assert entry.options["dry_run"] is True

    async def test_the_conversion_does_not_reload_the_entry(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        assert reloads == []
        assert entry.state is ConfigEntryState.LOADED

    async def test_the_entry_version_is_not_bumped(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        assert (entry.version, entry.minor_version) == (1, 1)

    async def test_the_entity_and_its_ids_are_the_same(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        entity = er.async_get(hass).async_get(
            er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{KEY}")
        )
        assert entity.entity_id == "sensor.givenergy_inverter_manager_water_heating_cheapest_source"
        assert entity.unique_id == f"{entry.entry_id}_{KEY}"

    async def test_a_cost_sensor_alone_is_converted_too(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        hass.states.async_set("sensor.oil_price", "1.37")
        entry = _entry({"oil_price_entity": "sensor.oil_price"})
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert entry.options["alt_heat_cost_entity"] == "sensor.oil_price"
        assert "alt_heat_cost" not in entry.options
        assert sensor(hass, entry).attributes["alt_cost_per_kwh"] == 0.1557

    async def test_reloading_does_not_convert_again(self, hass_in_scenario, reloads, conversions):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        converted = dict(entry.options)
        assert len(conversions) == 1
        assert conversions[0] is not None

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert conversions[1:] == [None, None]
        assert {k: entry.options[k] for k in converted if k.startswith("alt_")} == {
            k: v for k, v in converted.items() if k.startswith("alt_")
        }

    async def test_a_user_who_turned_it_off_after_the_conversion_stays_off(
        self, hass_in_scenario, reloads
    ):
        """Switching off keeps the cost. The next setup must not read it as a fresh oil price."""
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "alt_heat_enabled": False}
        )
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.options["alt_heat_enabled"] is False
        assert sensor(hass, entry) is None


class TestAnOilInstallReadsAsBefore:
    """The live install: 1.37 a litre. Every figure and sentence is the one 0.17 gave."""

    @pytest.fixture(params=[(MIDDAY, OLD_MIDDAY), (CHEAP_NIGHT, OLD_NIGHT)], ids=["midday", "night"])
    def case(self, request):
        return request.param

    @pytest.fixture
    def scenario(self, case):
        return case[0]

    async def test_the_state_and_attributes_match_the_old_ones(self, hass_in_scenario, case):
        hass = hass_in_scenario
        _scenario, old = case
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        await refresh(hass, entry)
        state = sensor(hass, entry)

        assert state.state == ("alternative" if old["state"] == "oil" else old["state"])
        for name, value in old.items():
            if name == "state":
                continue
            assert state.attributes[RENAMED.get(name, name)] == value, name

    async def test_no_old_attribute_name_is_left(self, hass_in_scenario, case):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        await refresh(hass, entry)
        names = set(sensor(hass, entry).attributes)
        assert not [name for name in names if "oil" in name], sorted(names)

    async def test_the_label_attribute_says_oil(self, hass_in_scenario, case):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert sensor(hass, entry).attributes["alt_label"] == "Oil"


class TestSetupWithTheNewKeys:
    @pytest.fixture
    def scenario(self):
        return MIDDAY

    NEW = {
        "alt_heat_enabled": True,
        "alt_heat_label": "Gas",
        "alt_heat_cost_unit": "kwh_heat",
        "alt_heat_cost": 0.08,
    }

    async def test_an_entry_with_the_new_keys_is_not_rewritten(
        self, hass_in_scenario, reloads, conversions
    ):
        hass = hass_in_scenario
        entry = _entry(dict(self.NEW))
        await set_up(hass, entry)
        assert conversions == [None]
        assert {key: entry.options[key] for key in self.NEW} == self.NEW
        assert not [key for key in entry.options if key.startswith("alt_") and key not in self.NEW]
        assert reloads == []

    async def test_a_gas_example_gives_advice_that_says_gas(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry(dict(self.NEW))
        await set_up(hass, entry)
        await refresh(hass, entry)
        state = sensor(hass, entry)
        assert state.state == "alternative"
        assert state.attributes["alt_label"] == "Gas"
        assert state.attributes["alt_cost_per_kwh"] == 0.08
        assert "Gas is cheaper than the grid now" in state.attributes["suggestion"]
        assert "run the gas water heating for about" in state.attributes["suggestion"]
        assert "oil" not in state.attributes["suggestion"].lower()

    async def test_the_cost_per_kwh_of_heat_is_not_converted_like_a_litre(
        self, hass_in_scenario, reloads
    ):
        hass = hass_in_scenario
        entry = _entry({**self.NEW, "alt_heat_cost": 0.30})
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert sensor(hass, entry).attributes["alt_cost_per_kwh"] == 0.30

    async def test_both_the_old_and_the_new_keys_leave_the_new_ones_in_charge(
        self, hass_in_scenario, reloads
    ):
        hass = hass_in_scenario
        entry = _entry({**self.NEW, "oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert entry.options["alt_heat_label"] == "Gas"
        assert entry.options["alt_heat_cost"] == 0.08
        assert sensor(hass, entry).attributes["alt_cost_per_kwh"] == 0.08

    async def test_an_install_without_oil_is_untouched(
        self, hass_in_scenario, reloads, conversions
    ):
        hass = hass_in_scenario
        entry = _entry({"vat_rate": 13.5, "oil_price_entity": ""})
        await set_up(hass, entry)
        assert conversions == [None]
        assert entry.options["vat_rate"] == 13.5
        assert entry.options["oil_price_entity"] == ""
        assert not [key for key in entry.options if key.startswith("alt_")]
        assert sensor(hass, entry) is None


class TestTheSwitchAndTheSensorComeAndGo:
    """The advice needs the immersion switch. The water temperature sensor only sharpens it."""

    @pytest.fixture
    def scenario(self):
        return MIDDAY

    async def test_without_the_switch_the_setting_is_kept_and_nothing_is_created(
        self, hass_in_scenario, caplog
    ):
        hass = hass_in_scenario
        data = full_config_data()
        data.pop("immersion_switch_entity")
        entry = _entry({"oil_price_per_litre": 1.37}, data)
        await set_up(hass, entry)
        assert entry.options["alt_heat_enabled"] is True
        assert sensor(hass, entry) is None
        assert entry.runtime_data.data.water_heating_advice is None
        assert "no advice until an immersion switch is set" in caplog.text
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    async def test_the_switch_added_later_starts_the_advice(self, hass_in_scenario):
        hass = hass_in_scenario
        data = full_config_data()
        data.pop("immersion_switch_entity")
        entry = _entry({"oil_price_per_litre": 1.37}, data)
        await set_up(hass, entry)
        assert sensor(hass, entry) is None

        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "immersion_switch_entity": "switch.immersion_heater"}
        )
        await hass.async_block_till_done()
        await refresh(hass, entry)
        assert sensor(hass, entry).state == "alternative"

    async def test_the_switch_removed_later_removes_the_advice_and_keeps_the_setting(
        self, hass_in_scenario
    ):
        hass = hass_in_scenario
        entry = _entry({"oil_price_per_litre": 1.37})
        await set_up(hass, entry)
        assert sensor(hass, entry) is not None

        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "immersion_switch_entity": ""}
        )
        await hass.async_block_till_done()
        assert sensor(hass, entry) is None
        assert entry.options["alt_heat_cost"] == 1.37

    async def test_without_the_temperature_sensor_the_advice_is_the_plain_sentence(
        self, hass_in_scenario
    ):
        hass = hass_in_scenario
        data = full_config_data()
        data.pop("immersion_temp_sensor_entity")
        entry = _entry({"oil_price_per_litre": 1.37}, data)
        await set_up(hass, entry)
        await refresh(hass, entry)
        text = sensor(hass, entry).attributes["suggestion"]
        assert text.startswith("Oil is cheaper than electricity until")
        assert "alt_keep_warm" not in sensor(hass, entry).attributes
        assert not [e for e in er.async_get(hass).entities.values() if "water_temperature" in e.entity_id]

    async def test_the_temperature_sensor_added_later_adds_the_keep_warm_run(
        self, hass_in_scenario
    ):
        hass = hass_in_scenario
        data = full_config_data()
        temp_entity = data.pop("immersion_temp_sensor_entity")
        entry = _entry({"oil_price_per_litre": 1.37}, data)
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert "alt_keep_warm" not in sensor(hass, entry).attributes

        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "immersion_temp_sensor_entity": temp_entity}
        )
        await hass.async_block_till_done()
        await refresh(hass, entry)
        attributes = sensor(hass, entry).attributes
        assert "run the oil water heating for about" in attributes["alt_keep_warm"]
