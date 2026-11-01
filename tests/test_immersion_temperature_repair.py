"""The repair for a hot water temperature sensor that reads nothing."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_LOWER_TEMP_SENSOR,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.temperature_feed import SILENT_CYCLES
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_IMMERSION_TEMPERATURE_NOT_REPORTING,
)
from tests.test_coordinator import FakeCoordinator, _cfg

UPPER = "sensor.cylinder_upper"
LOWER = "sensor.cylinder_lower"


@pytest.fixture
def coord():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()
    coordinator = FakeCoordinator(
        cfg=_cfg(**{CONF_IMMERSION_TEMP_SENSOR: UPPER, CONF_IMMERSION_LOWER_TEMP_SENSOR: LOWER})
    )
    coordinator.set_states({UPPER: "48.0", LOWER: "31.0"})
    return coordinator


def _cycles(coord, count: int, **overrides) -> None:
    cfg = {CONF_IMMERSION_TEMP_SENSOR: UPPER, CONF_IMMERSION_LOWER_TEMP_SENSOR: LOWER, **overrides}
    for _ in range(count):
        coord._check_temperature_sensors(cfg)


def _raised():
    return [
        c
        for c in ir.async_create_issue.call_args_list
        if c.args[2] == ISSUE_IMMERSION_TEMPERATURE_NOT_REPORTING
    ]


def _cleared():
    return [
        c
        for c in ir.async_delete_issue.call_args_list
        if c.args[2] == ISSUE_IMMERSION_TEMPERATURE_NOT_REPORTING
    ]


def test_sensors_that_read_raise_nothing(coord):
    _cycles(coord, SILENT_CYCLES + 2)

    assert _raised() == []


def test_a_sensor_that_stays_unavailable_raises_the_repair_naming_it(coord):
    coord.set_state(UPPER, "unavailable")

    _cycles(coord, SILENT_CYCLES - 1)
    assert _raised() == []
    _cycles(coord, 1)

    [call] = _raised()
    assert call.args[1] == DOMAIN
    assert call.kwargs["translation_placeholders"] == {"sensors": UPPER}
    assert call.kwargs["is_fixable"] is False


def test_unknown_and_a_missing_entity_count_as_nothing(coord):
    coord.set_state(UPPER, "unknown")
    del coord._states[LOWER]

    _cycles(coord, SILENT_CYCLES)

    [call] = _raised()
    assert call.kwargs["translation_placeholders"] == {"sensors": f"{UPPER}, {LOWER}"}


def test_the_repair_clears_when_every_sensor_reads_again(coord):
    coord.set_state(LOWER, "unavailable")
    _cycles(coord, SILENT_CYCLES)
    assert _raised()
    ir.async_delete_issue.reset_mock()

    coord.set_state(LOWER, "30.2")
    _cycles(coord, 1)

    assert _cleared()


def test_a_sensor_removed_from_the_options_no_longer_holds_the_repair(coord):
    coord.set_state(LOWER, "unavailable")
    _cycles(coord, SILENT_CYCLES)
    ir.async_delete_issue.reset_mock()

    coord._check_temperature_sensors({CONF_IMMERSION_TEMP_SENSOR: UPPER})

    assert _cleared()
