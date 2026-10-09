"""
The Ready by section of the Immersion view: the next hot water ready time.

The card is a markdown template that reads the attributes of the Immersion Water Temperature
sensor, so these tests render it with Jinja and the template functions Home Assistant provides
(tests/test_dashboard.py holds the stand-ins). Which devices show it is covered, with every
device combination, in tests/test_dashboard_devices.py.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.dashboard.templates import (
    planned_heating_template,
    ready_by_template,
)
from tests.dashboard_support import dashboard_dict, default_entity_ids
from tests.test_dashboard import _render

IDS = default_entity_ids()
SENSOR = IDS["immersion_water_temperature"]
SWITCH = IDS["immersion_schedule"]
ATTRS = {
    "ready_by": "07:00",
    "expected_ready": True,
    "heating_rate_c_per_h": 12.34,
}


def _text(**attrs) -> str:
    attributes = {(SENSOR, name): value for name, value in attrs.items()}
    return _render(ready_by_template(SENSOR), lambda entity: "48.0", attributes).strip()


class TestTheText:
    def test_it_gives_the_time_and_says_the_water_will_be_ready(self):
        text = _text(**ATTRS)
        assert text.startswith("**Next ready time 07:00**")
        assert "The water is expected to be at the target by then." in text

    def test_it_says_when_the_water_will_not_be_ready_in_time(self):
        text = _text(**{**ATTRS, "expected_ready": False})
        assert "The water is not expected to reach the target by then." in text

    def test_it_says_when_it_is_not_known_yet(self):
        text = _text(**{**ATTRS, "expected_ready": None})
        assert "Whether the water will be ready in time is not known yet." in text

    def test_it_gives_the_heating_rate_to_one_decimal_place(self):
        assert "Heating at about 12.3 °C an hour." in _text(**ATTRS)

    @pytest.mark.parametrize("rate", [None, "unknown"])
    def test_it_leaves_the_rate_out_when_there_is_none(self, rate):
        assert "Heating at" not in _text(**{**ATTRS, "heating_rate_c_per_h": rate})

    def test_with_no_ready_time_it_says_where_to_set_one(self):
        """The attributes are absent while no time is set, and a card cannot hide on that."""
        text = _text()
        assert text == (
            "No hot water ready time is set. Add one under Hot water ready by in the "
            "immersion options."
        )


class TestThePlannedHeatingLine:
    def _line(self, **attrs) -> str:
        attributes = {(SENSOR, name): value for name, value in attrs.items()}
        return _render(planned_heating_template(SENSOR), lambda entity: "48.0", attributes).strip()

    def test_it_prints_the_sentence_the_sensor_holds(self):
        sentence = "No heating planned for the 19:00 ready time (water 54.4°C, ready)."
        assert self._line(planned_heating=sentence) == sentence

    def test_it_reads_the_water_temperature_sensor(self):
        assert f"state_attr('{SENSOR}', 'planned_heating')" in planned_heating_template(SENSOR)

    def test_without_the_attribute_it_says_the_plan_waits_for_a_reading(self):
        """A card cannot hide on a missing attribute, so it says what it is waiting for."""
        assert self._line() == "The planned heating shows once the water temperature is read."


class TestTheSection:
    def _section(self) -> dict:
        view = next(v for v in dashboard_dict()["views"] if v["path"] == "immersion")
        return next(
            s
            for s in view["sections"]
            if any(c.get("heading") == "Ready by" for c in s["cards"])
        )

    def test_it_is_hidden_unless_scheduled_heating_is_on(self):
        conditions = self._section()["visibility"]
        assert {"condition": "state", "entity": SWITCH, "state": "on"} in conditions

    def test_it_shows_the_planned_heating_after_the_ready_time(self):
        cards = [c for c in self._section()["cards"] if c["type"] == "markdown"]
        assert "'ready_by'" in cards[0]["content"]
        assert "'planned_heating'" in cards[1]["content"]

    def test_it_waits_for_both_devices(self):
        entities = {c["entity"] for c in self._section()["visibility"]}
        assert {IDS["immersion_target_temp"], SENSOR} <= entities
