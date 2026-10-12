"""Every GivTCP system fixture is found, classified and given a controller as it should be.

Three kinds of fixture. One real one (a single-phase hybrid on GivTCP 3.6.3). Eight from GivTCP's
own test results, which run its real code over real wire captures, so the entity ids are the ones
GivTCP creates (from_harness.py). The rest are built from GivTCP's published datapoint list
(build.py). A test here keeps the committed files equal to what the builders make.
"""

from __future__ import annotations

import json

import pytest

from custom_components.givenergy_inverter_manager.core.system_types import (
    SystemKind,
    select_controller,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
    ENTITY_DOMAINS,
    ENTITY_SUFFIXES,
    discover_givtcp_inverters,
)
from tests.fixtures import givtcp_systems as fixtures
from tests.fixtures.givtcp_systems import build, from_harness

NAMES = fixtures.names()


def _selection(name: str):
    inverters = discover_givtcp_inverters(fixtures.states(name))
    return inverters, select_controller([i.facts() for i in inverters])


class TestTheFixtures:
    def test_the_committed_files_are_what_the_builder_makes(self):
        built = build.build()
        for name, fixture in built.items():
            assert json.loads(json.dumps(fixture)) == fixtures.raw(name), name

    def test_every_fixture_names_where_it_came_from(self):
        for name in NAMES:
            assert fixtures.raw(name)["provenance"] in ("real", "harness", "synthetic"), name
        real = [n for n in NAMES if fixtures.raw(n)["provenance"] == "real"]
        assert real == ["hybrid_gen3_two_batteries_3_6_3"]

    def test_no_fixture_holds_a_real_serial(self):
        text = "".join((fixtures.HERE / f"{n}.json").read_text().lower() for n in NAMES)
        for real_serial in ("fd2309f069", "dz2325g071", "dz2410g556"):
            assert real_serial not in text


HARNESS = [n for n in NAMES if fixtures.raw(n)["provenance"] == "harness"]

# The roles the wiring looks for that GivTCP does not publish under the name we look for, by
# GivTCP's own model. Each is what its real capture shows, not a guess.
MISSING_ROLES = {
    "harness_hybrid_gen1": [],
    "harness_hybrid_gen2": [],
    "harness_ac": [],
    "harness_all_in_one": [],
    # The capture has no battery attached, so there is no battery power or charge level to find.
    "harness_hybrid_hv_gen3": ["battery_power", "battery_soc"],
    # Three-phase publishes import_power and export_power, and battery_charge_power and
    # battery_discharge_power, where the wiring looks for one signed grid and battery power.
    "harness_hybrid_3ph": ["battery_power", "grid_power", "inverter_temp"],
    "harness_gateway": ["inverter_temp"],
    # An EMS reads and controls no battery of its own.
    "harness_ems": [
        "solar_power", "house_load", "inverter_temp", "target_soc", "enable_charge_target",
        "enable_charge_schedule", "charge_start_time", "charge_end_time", "battery_capacity_kwh",
        "battery_soc",
    ],
}


class TestTheHarnessFixtures:
    def test_there_is_one_for_each_model_the_generator_knows(self):
        assert HARNESS == sorted(f"harness_{m}" for m in from_harness.MODELS)

    def test_each_says_where_it_came_from(self):
        for name in HARNESS:
            raw = fixtures.raw(name)
            assert "GivTCP's own test results" in raw["source"], name
            assert raw["givtcp_version"] == from_harness.GIVTCP_VERSION, name

    @pytest.mark.parametrize("name", HARNESS)
    def test_the_wiring_finds_what_the_real_model_publishes(self, name):
        states = fixtures.states(name)
        prefix = _selection(name)[1].controller.prefix
        roles = {**ENTITY_SUFFIXES, "battery_soc": "_soc"}
        missing = []
        for role, suffix in roles.items():
            domain = ENTITY_DOMAINS.get(role, "sensor")
            suffixes = ["_soc", "_battery_soc"] if role == "battery_soc" else [suffix]
            if not any(f"{domain}.{prefix}{s}" in states for s in suffixes):
                missing.append(role)
        assert sorted(missing) == sorted(MISSING_ROLES[name])


@pytest.mark.parametrize("name", [n for n in NAMES if fixtures.raw(n).get("expected")])
class TestEachSynthetic:
    def test_it_is_classified_and_the_right_device_is_chosen(self, name):
        expected = fixtures.raw(name)["expected"]
        inverters, selection = _selection(name)

        assert selection.controller is not None
        assert selection.controller.kind is SystemKind(expected["kind"])
        assert selection.controller.serial.upper() == expected["controller"]
        assert selection.ask is expected["ask"]
        if expected.get("devices"):
            assert len(inverters) == expected["devices"]
        if "prefix" in expected:
            assert selection.controller.prefix == expected["prefix"]
        if expected["modules"] is not None:
            assert selection.controller.modules == expected["modules"]


class TestTheRealHybrid:
    NAME = "hybrid_gen3_two_batteries_3_6_3"

    def test_it_is_found_with_everything_the_plan_needs(self):
        [inverter], selection = _selection(self.NAME)
        assert inverter.serial == "AB1234G567"
        assert inverter.kind is SystemKind.HYBRID
        assert inverter.confidence == "high"
        assert inverter.givtcp_version == "3.6.3"
        assert inverter.is_fully_configured and inverter.has_charge_scheduling
        assert inverter.battery_capacity_kwh == pytest.approx(19.046)
        assert inverter.modules == 2
        assert selection.controller is not None and not selection.ask

    def test_the_battery_modules_and_the_meter_are_not_inverters(self):
        inverters, _ = _selection(self.NAME)
        assert [i.serial for i in inverters] == ["AB1234G567"]


class TestWhatTheKindsDecide:
    def test_a_custom_prefix_is_found_and_its_wiring_uses_it(self):
        [inverter], _ = _selection("hybrid_custom_prefix_3_6_3")
        assert inverter.entities["battery_soc"] == "sensor.house_ab1234g567_soc"
        assert inverter.entities["target_soc"] == "number.house_ab1234g567_target_soc"

    def test_a_gateway_over_parallel_units_is_managed_and_nothing_is_asked(self):
        _, selection = _selection("gateway_parallel_two_aio_3_6_3")
        assert selection.controller.kind is SystemKind.GATEWAY
        assert selection.controller.parallel_units == 2
        assert selection.ask is False

    def test_a_gateway_with_one_unit_gives_way_to_the_all_in_one(self):
        inverters, selection = _selection("all_in_one_and_gateway_3_6_3")
        assert {i.kind for i in inverters} == {SystemKind.ALL_IN_ONE, SystemKind.GATEWAY}
        assert selection.controller.kind is SystemKind.ALL_IN_ONE
        assert [o.kind for o in selection.others] == [SystemKind.GATEWAY]

    def test_two_inverters_are_never_added_together_and_the_user_is_asked(self):
        inverters, selection = _selection("two_hybrids_3_6_3")
        assert len(inverters) == 2
        assert selection.ask is True
        assert len(selection.others) == 1

    def test_an_ems_has_no_charge_controls_or_state_of_charge_to_wire(self):
        [ems], _ = _selection("ems_3_6_3")
        assert ems.kind is SystemKind.EMS
        assert not ems.is_fully_configured
        assert not ems.has_charge_scheduling

    def test_a_ghost_battery_slot_is_not_a_module(self):
        [inverter], _ = _selection("hybrid_with_ghost_battery_3_6_3")
        assert inverter.modules == 2

    def test_an_ev_charger_beside_the_inverter_is_not_an_inverter(self):
        inverters, _ = _selection("hybrid_with_ev_charger_3_6_3")
        assert [i.serial for i in inverters] == ["AB1234G567"]

    def test_the_hv_gen3_changes_kind_across_the_upgrade(self):
        [before], _ = _selection("hv_gen3_before_3_6")
        [after], _ = _selection("hv_gen3_after_3_6")
        assert before.kind is SystemKind.THREE_PHASE
        assert before.confidence == "medium"  # the type text says All-In-One, the entities disagree
        assert after.kind is SystemKind.HYBRID
        assert before.serial == after.serial


class TestTheDevicePrefix:
    """The prefix the entities derived from the serial are read under."""

    def _cfg(self, name: str) -> dict:
        from custom_components.givenergy_inverter_manager.wizard.wiring import (
            wiring_from,
            with_serial,
        )

        [inverter], _ = _selection(name)
        return with_serial(wiring_from(inverter), inverter.serial)

    def test_the_default_prefix_is_found_from_the_wiring(self):
        from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
            device_prefix,
        )

        assert device_prefix(self._cfg("hybrid_gen3_two_batteries_3_6_3")) == "givtcp_ab1234g567"

    def test_a_custom_prefix_is_found_from_the_wiring(self):
        from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
            device_prefix,
        )

        assert device_prefix(self._cfg("hybrid_custom_prefix_3_6_3")) == "house_ab1234g567"

    def test_hand_picked_sensors_with_other_names_fall_back_to_the_serial(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_BATTERY_SOC,
            CONF_INVERTER_SERIAL,
            CONF_SOLAR_POWER,
        )
        from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
            device_prefix,
        )

        cfg = {
            CONF_INVERTER_SERIAL: "AB1234G567",
            CONF_BATTERY_SOC: "sensor.battery_soc",
            CONF_SOLAR_POWER: "sensor.solar",
        }
        assert device_prefix(cfg) == "givtcp_AB1234G567"

    def test_no_serial_and_no_wiring_gives_no_prefix(self):
        from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
            device_prefix,
        )

        assert device_prefix({}) == ""
