"""The setup checklist and the dry run banner on the Power Flow tab.

The checklist is a markdown card drawn from the `items` attribute of the Setup Progress sensor.
It shows while the sensor says incomplete and has no dismiss button. The dry run banner shows the
last skipped action and tonight's charge plan, read from the sensors that hold them. Both use a
classic state condition, which works on the Home Assistant floor.
"""

from __future__ import annotations

import pytest
from jinja2 import Environment

from custom_components.givenergy_inverter_manager.core.devices import Device
from tests.dashboard_support import FakeRegistry, dashboard_dict, default_entity_ids
from tests.dashboard_visibility import generated_for, seen, states_with

IDS = default_entity_ids()
PROGRESS = IDS["setup_progress"]
CHECKLIST = "Finish setting up"
BANNER = "Dry run is on"


def _power_flow(dashboard: dict) -> dict:
    return next(v for v in dashboard["views"] if v["path"] == "power-flow")


def _section(dashboard: dict, heading: str) -> dict | None:
    return next(
        (s for s in _power_flow(dashboard)["sections"] if s["cards"][0].get("heading") == heading),
        None,
    )


def _render(content: str, attrs: dict, states: dict | None = None) -> str:
    """Render a markdown card with the template functions the cards use."""
    states = states or {}
    return Environment().from_string(content).render(
        states=lambda entity: states.get(entity, "unknown"),
        state_attr=lambda entity, name: attrs.get((entity, name)),
    )


def _items(*rows) -> dict:
    """The attributes of the Setup Progress sensor for (label, done, required) rows."""
    items = [
        {"key": label.lower(), "label": label, "done": done, "required": required}
        for label, done, required in rows
    ]
    return {(PROGRESS, "items"): items}


class TestTheChecklistSection:
    def test_it_sits_between_the_banner_and_the_flow(self):
        headings = [s["cards"][0].get("heading") for s in _power_flow(dashboard_dict())["sections"]]
        assert headings == ["Now", BANNER, CHECKLIST, "Live power flow", "Energy today", "Devices"]

    def test_it_holds_a_heading_and_one_markdown_card(self):
        section = _section(dashboard_dict(), CHECKLIST)
        assert [c["type"] for c in section["cards"]] == ["heading", "markdown"]

    def test_it_shows_only_while_the_sensor_says_incomplete(self):
        section = _section(dashboard_dict(), CHECKLIST)
        assert section["visibility"] == [
            {"condition": "state", "entity": PROGRESS, "state": "incomplete"}
        ]

    def test_it_uses_only_the_classic_state_condition(self):
        """The wider visibility conditions need a newer Home Assistant than the floor."""
        section = _section(dashboard_dict(), CHECKLIST)
        assert {c["condition"] for c in section["visibility"]} == {"state"}

    def test_it_has_no_dismiss_button(self):
        text = str(_section(dashboard_dict(), CHECKLIST))
        assert "dismiss" not in text.lower()
        assert not [c for c in _section(dashboard_dict(), CHECKLIST)["cards"] if c["type"] == "button"]
        assert "tap_action" not in text

    def test_it_is_left_out_when_the_sensor_is_missing(self):
        registry = FakeRegistry(enable_all=True, absent={"setup_progress"})
        assert _section(dashboard_dict(registry=registry), CHECKLIST) is None

    def test_everyone_gets_it_not_only_administrators(self):
        for is_admin in (True, False):
            assert _section(dashboard_dict(is_admin=is_admin), CHECKLIST) is not None

    @pytest.mark.parametrize(
        ("progress", "shown"), [("incomplete", True), ("complete", False), ("unavailable", False)]
    )
    def test_the_frontend_hides_it_when_the_required_items_are_done(self, progress, shown):
        dashboard = generated_for(ev=True, switch=True, sensor=True)
        states = states_with(Device) | {PROGRESS: progress}
        headings = [s["cards"][0].get("heading") for s in _power_flow(seen(dashboard, states))["sections"]]
        assert (CHECKLIST in headings) is shown

    def test_the_banner_and_the_checklist_show_together_on_a_new_install(self):
        dashboard = generated_for(ev=True, switch=True, sensor=True)
        states = states_with(Device) | {PROGRESS: "incomplete", IDS["dry_run_active"]: "True"}
        headings = [s["cards"][0].get("heading") for s in _power_flow(seen(dashboard, states))["sections"]]
        assert headings[:3] == ["Now", BANNER, CHECKLIST]


class TestTheChecklistText:
    @pytest.fixture
    def content(self) -> str:
        return next(
            c["content"] for c in _section(dashboard_dict(), CHECKLIST)["cards"] if c["type"] == "markdown"
        )

    def test_it_reads_the_items_attribute_of_the_progress_sensor(self, content):
        assert f"state_attr('{PROGRESS}', 'items')" in content

    def test_each_required_item_is_done_or_to_do(self, content):
        text = _render(content, _items(("Tariff set", True, True), ("Solar forecast added", False, True)))
        assert "- Done: Tariff set" in text
        assert "- To do: Solar forecast added" in text

    def test_optional_items_that_are_not_done_appear_once_as_available(self, content):
        text = _render(
            content,
            _items(("Tariff set", True, True), ("Hot water", False, False), ("EV charger", False, False)),
        )
        assert text.count("Available: Hot water, EV charger") == 1
        assert "Hot water" not in text.split("Available")[0]

    def test_an_optional_item_that_is_done_is_not_listed(self, content):
        text = _render(content, _items(("Tariff set", True, True), ("Hot water", True, False)))
        assert "Hot water" not in text
        assert "Available" not in text

    def test_no_available_line_when_every_optional_item_is_done(self, content):
        text = _render(content, _items(("Hot water", True, False), ("EV charger", True, False)))
        assert "Available" not in text

    def test_the_available_line_is_in_smaller_text(self, content):
        text = _render(content, _items(("Hot water", False, False)))
        assert "<small>Available: Hot water</small>" in text

    def test_it_renders_nothing_before_the_sensor_has_items(self, content):
        assert _render(content, {}).strip() == ""

    def test_a_required_item_is_never_listed_as_available(self, content):
        text = _render(content, _items(("Tariff set", False, True)))
        assert "Available" not in text


class TestTheDryRunBanner:
    @staticmethod
    def _text(dashboard: dict) -> str:
        section = _section(dashboard, BANNER)
        return next(c["content"] for c in section["cards"] if c["type"] == "markdown")

    def test_it_shows_the_last_skipped_action_and_tonights_plan(self):
        text = _render(
            self._text(dashboard_dict()),
            {},
            {
                IDS["dry_run_last_skipped"]: "Would set the charge target to 80%",
                IDS["charge_plan"]: "Target 78% · Add 34% · Cost €0.51",
                IDS["dry_run_active"]: "True",
            },
        )
        assert "**Last skipped action:** Would set the charge target to 80%" in text
        assert "**Tonight's charge plan:** Target 78% · Add 34% · Cost €0.51" in text

    def test_the_plan_line_follows_the_last_skipped_line(self):
        content = self._text(dashboard_dict())
        assert content.index("Last skipped action") < content.index("Tonight's charge plan")

    def test_the_lines_read_the_entities_that_hold_the_values(self):
        content = self._text(dashboard_dict())
        assert IDS["dry_run_last_skipped"] in content
        assert IDS["charge_plan"] in content

    def test_without_the_plan_sensor_the_banner_keeps_its_other_lines(self):
        registry = FakeRegistry(enable_all=True, absent={"charge_plan"})
        content = self._text(dashboard_dict(registry=registry))
        assert "Tonight's charge plan" not in content
        assert "Last skipped action" in content

    def test_it_still_shows_only_while_dry_run_is_active(self):
        assert _section(dashboard_dict(), BANNER)["visibility"] == [
            {"condition": "state", "entity": IDS["dry_run_active"], "state": "True"}
        ]

    def test_it_uses_no_condition_newer_than_the_floor(self):
        conditions = {c["condition"] for c in _section(dashboard_dict(), BANNER)["visibility"]}
        assert conditions <= {"state", "numeric_state", "screen", "user", "and", "or"}
