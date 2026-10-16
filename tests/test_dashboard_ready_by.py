"""
The Plan card of the Hot water view: the planned heating for the next ready time.

The card is a markdown template that reads the planned_heating attribute of the Immersion Water
Temperature sensor, so these tests render it with Jinja and the template functions Home
Assistant provides (tests/test_dashboard.py holds the stand-ins). Which devices show the Plan card is covered, with
every device combination, in tests/test_dashboard_devices.py.
"""

from __future__ import annotations

from tests.dashboard_support import dashboard_dict, default_entity_ids
from tests.test_dashboard import _render

IDS = default_entity_ids()
SENSOR = IDS["immersion_water_temperature"]
SWITCH = IDS["immersion_schedule"]


class TestThePlanCard:
    def _card(self) -> dict:
        view = next(v for v in dashboard_dict()["views"] if v["path"] == "immersion")
        section = next(
            s for s in view["sections"] if any(c.get("heading") == "Plan" for c in s["cards"])
        )
        return next(c for c in section["cards"] if c["type"] == "markdown")

    def test_it_is_hidden_unless_scheduled_heating_is_on(self):
        conditions = self._card()["visibility"]
        assert {"condition": "state", "entity": SWITCH, "state": "on"} in conditions

    def test_it_prints_the_planned_heating_which_names_the_ready_time(self):
        card = self._card()
        sentence = "Heating from 05:10 for the 07:00 ready time (water 41.2°C)."
        attributes = {(SENSOR, "planned_heating"): sentence}
        assert _render(card["content"], lambda entity: "48.0", attributes) == sentence
        assert _render(card["content"], lambda entity: "48.0", {}) == (
            "The planned heating shows once the water temperature is read."
        )

    def test_it_waits_for_both_devices(self):
        entities = {c["entity"] for c in self._card()["visibility"]}
        assert {IDS["immersion_target_temp"], SENSOR} <= entities
