"""The inverter wiring helpers and the detection the wizards start from."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
)
from custom_components.givenergy_inverter_manager.discovery import GivTCPInverter
from custom_components.givenergy_inverter_manager.wizard.detect import best_inverter, detect
from custom_components.givenergy_inverter_manager.wizard.wiring import (
    MANUAL_SERIAL,
    WIRING_KEYS,
    WIRING_OPTIONAL,
    serial_in_entity_id,
    serials_in_wiring,
    serials_match,
    wiring_from,
    with_serial,
)

PREFIX = "givtcp_ab1234g567"


def _states(*entity_ids: str) -> dict:
    return {e: SimpleNamespace(state="1", attributes={}) for e in entity_ids}


def _five(prefix: str = PREFIX) -> dict:
    return {
        CONF_SOLAR_POWER: f"sensor.{prefix}_pv_power",
        CONF_BATTERY_SOC: f"sensor.{prefix}_soc",
        CONF_BATTERY_POWER: f"sensor.{prefix}_battery_power",
        CONF_GRID_POWER: f"sensor.{prefix}_grid_power",
        CONF_HOUSE_LOAD: f"sensor.{prefix}_load_power",
    }


@pytest.mark.parametrize(
    ("entity_id", "serial"),
    [
        ("sensor.givtcp_ab1234g567_pv_power", "ab1234g567"),
        ("number.givtcp_ab1234g567_target_soc", "ab1234g567"),
        ("select.givtcp_cd5678h901_charge_start_time_slot_1", "cd5678h901"),
        ("sensor.rewired_solar", None),
        ("", None),
    ],
)
def test_the_serial_in_an_entity_id(entity_id, serial):
    assert serial_in_entity_id(entity_id) == serial


def test_the_serials_the_chosen_entities_carry():
    mixed = {**_five(), CONF_GRID_POWER: "sensor.givtcp_cd5678h901_grid_power"}

    assert serials_in_wiring(_five()) == {"ab1234g567"}
    assert serials_in_wiring(mixed) == {"ab1234g567", "cd5678h901"}
    assert serials_in_wiring({CONF_SOLAR_POWER: "sensor.other"}) == set()


@pytest.mark.parametrize(
    ("serials", "unique_id", "match"),
    [
        ({"ab1234g567"}, "ab1234g567", True),
        ({"ab1234g567"}, "AB1234G567", True),
        ({"ab1234g567", "cd5678h901"}, "ab1234g567", False),
        ({"cd5678h901"}, "ab1234g567", False),
        (set(), "ab1234g567", True),
        ({"cd5678h901"}, MANUAL_SERIAL, True),
        ({"cd5678h901"}, None, True),
    ],
)
def test_the_serials_match_the_unique_id_ignoring_case(serials, unique_id, match):
    assert serials_match(serials, unique_id) is match


def test_the_wiring_keys_are_the_five_required_and_the_six_optional():
    assert len(WIRING_KEYS) == 11
    assert len(WIRING_OPTIONAL) == 6
    assert set(_five()) < set(WIRING_KEYS)


def test_the_wiring_of_a_discovered_inverter_uses_the_stored_keys():
    inverter = GivTCPInverter(
        serial="ab1234g567",
        prefix=PREFIX,
        display_name="GivTCP ab1234g567",
        entities={"solar_power": "sensor.a", "target_soc": "number.b", "battery_capacity_kwh": "sensor.c"},
    )

    assert wiring_from(inverter) == {"solar_power_entity": "sensor.a", "target_soc_entity": "number.b"}
    assert with_serial({"x": "y"}, "ab1") == {"x": "y", CONF_INVERTER_SERIAL: "ab1"}


def test_detect_finds_the_inverter_a_forecast_a_charger_and_immersion_switches():
    states = _states(
        f"sensor.{PREFIX}_invertor_serial_number",
        f"sensor.{PREFIX}_pv_power",
        f"sensor.{PREFIX}_soc",
        f"sensor.{PREFIX}_battery_power",
        f"sensor.{PREFIX}_grid_power",
        f"sensor.{PREFIX}_load_power",
        "sensor.energy_production_tomorrow",
        "switch.immersion_heater",
    )

    found = detect(states)

    assert [i.serial for i in found.inverters] == ["1"]  # the serial sensor's state
    assert found.inverters[0].is_fully_configured
    assert found.forecast.provider == "Forecast.Solar"
    assert found.immersion_candidates == ("switch.immersion_heater",)
    assert found.ev_chargers == ()


def test_the_best_inverter_prefers_one_with_every_required_sensor():
    partial = GivTCPInverter("a", "p", "A", entities={"solar_power": "sensor.x"})
    complete = GivTCPInverter(
        "b",
        "q",
        "B",
        entities={
            key: f"sensor.{key}"
            for key in ("solar_power", "battery_soc", "battery_power", "grid_power", "house_load")
        },
    )

    assert best_inverter(detect({})) is None
    assert best_inverter(SimpleNamespace(inverters=(partial, complete))) is complete
    assert best_inverter(SimpleNamespace(inverters=(partial,))) is partial
