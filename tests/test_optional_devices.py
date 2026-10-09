"""
The entities that need an optional device are created only while the device is present.

The real-Home-Assistant checks (setup, a device appearing later, an options change, orphan
removal) are in tests/ha_e2e/test_optional_devices_e2e.py. These pin the table of what needs
what, and the add and remove logic against doubles.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.givenergy_inverter_manager import optional_devices as od
from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.sensor_descriptions import SENSOR_DESCRIPTIONS

EV = Device.EV_CHARGER
SWITCH = Device.IMMERSION_SWITCH
SENSOR = Device.IMMERSION_SENSOR
THERMOSTAT = Device.IMMERSION_THERMOSTAT


def _needing(device: Device) -> set[str]:
    keys = {d.key for d in SENSOR_DESCRIPTIONS if d.requires == device}
    return keys | {e.key for e in od.DEVICE_ENTITIES if e.requires == device}


class TestWhatNeedsWhat:
    """The table of entities that exist only with a device."""

    def test_the_ev_charger_has_its_sensors_and_the_zappi_totals(self):
        assert _needing(EV) == {
            "ev_charger_state",
            "ev_power",
            "ev_session_energy",
            "ev_km_charged_today",
            "ev_cost_per_km_today",
            "ev_draining_battery",
            "ev_protection_reason",
            "ev_charging_source",
            "ev_solar_surplus_available",
            "zappi_today",
            "zappi_cost_today",
        }

    def test_the_immersion_switch_has_its_energy_money_and_controls(self):
        assert _needing(SWITCH) == {
            "immersion_power",
            "immersion_today",
            "immersion_cost_today",
            "immersion_savings_today",
            "immersion_savings_yesterday",
            "immersion_savings_this_week",
            "immersion_savings_this_month",
            "immersion_solar_kwh_today",
            "auto_immersion",
            "immersion_managed",
        }

    def test_the_water_temperature_follows_the_sensor(self):
        assert _needing(SENSOR) == {"immersion_water_temperature"}

    def test_the_temperature_controls_need_the_switch_and_the_sensor(self):
        assert _needing(THERMOSTAT) == {
            "immersion_cheap_window",
            "immersion_target_temp",
            "immersion_min_temp",
            "immersion_hysteresis",
        }

    def test_every_ev_sensor_that_reads_the_charger_is_unavailable_without_one(self):
        """The EV sensors that need a charger say so too, so one that is gone reads unavailable."""
        for description in SENSOR_DESCRIPTIONS:
            if description.requires == EV and description.key.startswith("ev_"):
                if description.key in ("ev_km_charged_today", "ev_cost_per_km_today"):
                    continue
                data = SimpleNamespace(ev_available=False)
                assert description.available_fn(data) is False, description.key

    def test_the_entities_the_integration_always_has_need_no_device(self):
        always = {d.key for d in SENSOR_DESCRIPTIONS if d.requires is None}
        assert {"solar_power", "battery_soc", "immersion_divert_reason", "house_cost_today"} <= always

    def test_no_key_needs_two_devices(self):
        keys = [k for device in Device for k in _needing(device)]
        assert len(keys) == len(set(keys))

    def test_the_switch_and_number_names_are_the_ones_the_entities_use(self):
        from custom_components.givenergy_inverter_manager import number, switch

        assert switch.GivEnergyAutoImmersionSwitch._attr_name == od.AUTO_IMMERSION.name
        assert switch.GivEnergyImmersionControlSwitch._attr_name == od.IMMERSION_MANAGED.name
        assert (
            switch.GivEnergyImmersionCheapWindowSwitch._attr_name == od.IMMERSION_CHEAP_WINDOW.name
        )
        assert number.ImmersionTargetTempNumber._attr_name == od.IMMERSION_TARGET.name
        assert number.ImmersionMinTempNumber._attr_name == od.IMMERSION_MINIMUM.name
        assert number.ImmersionHysteresisNumber._attr_name == od.IMMERSION_RESTART_GAP.name


def _entry(config=None, brand=None):
    """A config entry double whose coordinator reports a discovered charger brand."""
    listeners = []
    coordinator = SimpleNamespace(
        ev_charger_brand=brand,
        async_add_listener=lambda callback: listeners.append(callback) or (lambda: None),
    )
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = dict(config or {})
    entry.options = {}
    entry.runtime_data = coordinator
    return entry, coordinator, listeners


class TestAddingEntities:
    def _add(self, entry):
        added: list[list[str]] = []
        builds: list[Device] = []

        def build(device):
            builds.append(device)
            return [f"{device.value}-entity"]

        od.async_add_entities_per_device(entry, lambda entities: added.append(list(entities)), build)
        return added, builds

    def test_nothing_is_added_for_an_install_with_no_device(self):
        entry, _, _ = _entry()
        added, builds = self._add(entry)
        assert added == []
        assert builds == []

    def test_the_devices_present_at_setup_are_added_once(self):
        entry, _, listeners = _entry({CONF_IMMERSION_SWITCH: "switch.heater"})
        added, _ = self._add(entry)
        assert added == [["immersion_switch-entity"]]
        listeners[0]()  # a later update adds nothing more
        assert added == [["immersion_switch-entity"]]

    def test_the_thermostat_is_added_only_with_the_switch_and_the_sensor(self):
        entry, _, _ = _entry({CONF_IMMERSION_SWITCH: "s", CONF_IMMERSION_TEMP_SENSOR: "t"})
        added, builds = self._add(entry)
        assert set(builds) == {SWITCH, SENSOR, THERMOSTAT}
        assert len(added[0]) == 3

    def test_a_charger_found_later_is_added_when_discovery_succeeds(self):
        entry, coordinator, listeners = _entry()
        added, _ = self._add(entry)
        listeners[0]()
        assert added == []
        coordinator.ev_charger_brand = "myenergi_zappi"
        listeners[0]()
        assert added == [["ev_charger-entity"]]
        listeners[0]()
        assert added == [["ev_charger-entity"]]

    def test_the_listener_is_removed_when_the_entry_unloads(self):
        entry, _, _ = _entry()
        self._add(entry)
        entry.async_on_unload.assert_called_once()


class _Registry:
    """The entity registry calls remove_orphaned_entities makes."""

    def __init__(self, existing):
        self.existing = dict(existing)
        self.removed: list[str] = []

    def async_get_entity_id(self, platform, domain, unique_id):
        assert domain == DOMAIN
        return self.existing.get((platform, unique_id))

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


def _registry_with_every_device_entity(entry_id="entry1"):
    keys = list(od._device_entities())
    return _Registry({(p, f"{entry_id}_{k}"): f"{p}.{k}" for p, k, _ in keys})


class TestRemovingOrphans:
    def _remove(self, entry, registry, *, running=True, chargers=()):
        hass = MagicMock()
        hass.is_running = running
        hass.states.async_all.return_value = []
        with (
            patch.object(od.er, "async_get", return_value=registry),
            patch.object(od, "discover_ev_chargers", return_value=list(chargers)),
        ):
            od.remove_orphaned_entities(hass, entry)
        return {e.split(".", 1)[1] for e in registry.removed}

    def test_every_device_entity_goes_when_no_device_is_left(self):
        entry, _, _ = _entry()
        removed = self._remove(entry, _registry_with_every_device_entity())
        assert removed == _needing(EV) | _needing(SWITCH) | _needing(SENSOR) | _needing(THERMOSTAT)

    def test_the_entities_of_a_device_still_present_stay(self):
        entry, _, _ = _entry({CONF_IMMERSION_SWITCH: "switch.heater"})
        removed = self._remove(entry, _registry_with_every_device_entity())
        assert removed.isdisjoint(_needing(SWITCH))
        assert _needing(THERMOSTAT) <= removed
        assert _needing(SENSOR) <= removed

    def test_removing_the_sensor_removes_the_thermostat_but_keeps_the_switch_entities(self):
        entry, _, _ = _entry({CONF_IMMERSION_SWITCH: "switch.heater"})
        removed = self._remove(entry, _registry_with_every_device_entity())
        assert {"immersion_target_temp", "immersion_water_temperature"} <= removed
        assert "immersion_managed" not in removed

    def test_a_charger_the_coordinator_has_not_counted_yet_keeps_its_entities(self):
        """Discovery runs on the coordinator's second update. A scan of the states answers now."""
        entry, _, _ = _entry()
        removed = self._remove(entry, _registry_with_every_device_entity(), chargers=["zappi"])
        assert removed.isdisjoint(_needing(EV))

    def test_while_home_assistant_starts_the_ev_entities_are_kept(self):
        """The charger's own integration may not have loaded. Its entities come back later."""
        entry, _, _ = _entry()
        removed = self._remove(entry, _registry_with_every_device_entity(), running=False)
        assert removed.isdisjoint(_needing(EV))
        assert _needing(SWITCH) <= removed

    def test_a_charger_that_is_gone_after_startup_loses_its_entities(self):
        entry, _, _ = _entry()
        removed = self._remove(entry, _registry_with_every_device_entity(), running=True)
        assert _needing(EV) <= removed

    def test_an_entity_that_was_never_created_is_not_an_error(self):
        entry, _, _ = _entry()
        assert self._remove(entry, _Registry({})) == set()


@pytest.mark.parametrize("entity", od.DEVICE_ENTITIES, ids=lambda e: e.key)
def test_each_switch_and_number_has_a_name_and_a_platform(entity):
    assert entity.platform in ("switch", "number")
    assert entity.name
