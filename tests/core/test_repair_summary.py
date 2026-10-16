"""The Active Repairs titles and the markdown summary the dashboard shows."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.repair_summary import (
    RepairIssue,
    fill_placeholders,
    issue_title,
    repairs_summary,
)

PAUSE = RepairIssue(
    "charge_blocked_by_pause", "The battery pause stops tonight's charge", "warning", False
)
SLOTS = RepairIssue("other_charge_slots_active", "Other charge slots are active", "warning", True)


class TestSummary:
    def test_one_bold_line_per_issue_then_the_link(self):
        assert repairs_summary([PAUSE, SLOTS]) == (
            "- **The battery pause stops tonight's charge**\n"
            "- **Other charge slots are active**\n"
            "[Open Repairs](/config/repairs)"
        )

    def test_one_issue(self):
        assert repairs_summary([PAUSE]) == (
            "- **The battery pause stops tonight's charge**\n[Open Repairs](/config/repairs)"
        )

    def test_no_issue_is_empty_text(self):
        assert repairs_summary([]) == ""


class TestTitles:
    def test_placeholders_are_filled(self):
        assert fill_placeholders("Slot {slot} is set", {"slot": "2"}) == "Slot 2 is set"

    def test_a_placeholder_with_no_value_is_left_as_it_is(self):
        assert fill_placeholders("Slot {slot} at {time}", {"slot": "2"}) == "Slot 2 at {time}"

    def test_no_placeholders_given(self):
        assert fill_placeholders("Slot {slot}", None) == "Slot {slot}"

    def test_a_missing_translation_falls_back_to_the_issue_id(self):
        assert issue_title(None, None, "write_not_confirmed") == "write_not_confirmed"
        assert issue_title("", {"a": "b"}, "write_not_confirmed") == "write_not_confirmed"

    def test_a_translation_is_used_with_its_placeholders(self):
        assert issue_title("Pause {name}", {"name": "PauseBoth"}, "x") == "Pause PauseBoth"


def test_the_attribute_shape():
    assert SLOTS.as_attribute() == {
        "issue_id": "other_charge_slots_active",
        "title": "Other charge slots are active",
        "severity": "warning",
        "fixable": True,
    }
