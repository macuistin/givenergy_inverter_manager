"""The optional lower hot water thermometer: read for the graphs, never used to decide."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_LOWER_TEMP_SENSOR,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from tests.conftest import _raw, _run
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

SWITCH = "switch.heater"
UPPER = "sensor.cylinder_upper"
LOWER = "sensor.cylinder_lower"


def _coord(**overrides) -> FakeCoordinator:
    config = {CONF_IMMERSION_SWITCH: SWITCH, CONF_IMMERSION_TEMP_SENSOR: UPPER, **overrides}
    coord = FakeCoordinator(cfg=_cfg(**config))
    coord.set_states({**_default_states(), SWITCH: "off", UPPER: "48.0"})
    return coord


async def test_the_lower_reading_reaches_the_snapshot():
    coord = _coord(**{CONF_IMMERSION_LOWER_TEMP_SENSOR: LOWER})
    coord.set_state(LOWER, "31.4")

    data = await coord.run_cycle()

    assert data.immersion_lower_temp == 31.4


async def test_without_the_option_there_is_no_lower_reading():
    coord = _coord()
    coord.set_state(LOWER, "31.4")

    assert (await coord.run_cycle()).immersion_lower_temp is None


async def test_an_unreadable_lower_sensor_marks_nothing_unavailable():
    coord = _coord(**{CONF_IMMERSION_LOWER_TEMP_SENSOR: LOWER})
    coord.set_state(LOWER, "unavailable")

    data = await coord.run_cycle()

    assert data.immersion_lower_temp is None
    assert data.immersion_temp == 48.0


def test_the_decision_does_not_depend_on_the_lower_reading():
    cold = _run(raw=_raw(immersion_temp=44.0, immersion_lower_temp=10.0))[0]
    warm = _run(raw=_raw(immersion_temp=44.0, immersion_lower_temp=50.0))[0]
    none = _run(raw=_raw(immersion_temp=44.0, immersion_lower_temp=None))[0]

    assert cold.should_divert_immersion == warm.should_divert_immersion
    assert cold.should_divert_immersion == none.should_divert_immersion
    assert cold.divert_reason == warm.divert_reason == none.divert_reason


def test_the_sensor_rounds_to_one_place_and_reads_unknown_without_a_value():
    data = CoordinatorData()
    assert values.immersion_lower_temperature(data) is None
    data.immersion_lower_temp = 31.449
    assert values.immersion_lower_temperature(data) == 31.4
