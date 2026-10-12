"""The suggested alternative heating schedule line in its section of the Immersion view.

The line is a markdown card that reads attributes of the cheapest source sensor. A Lovelace
condition cannot test for an attribute, so the card itself says when the integration is still
learning or has nothing to suggest. The section's own conditions (alternative heating with a cost,
and an immersion switch) hide the line with it. The suggestion line above it is not changed.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import ALT_HEAT_SCHEDULE_MIN_DAYS
from custom_components.givenergy_inverter_manager.dashboard.templates import (
    alt_heat_schedule_template,
)
from tests.dashboard_visibility import seen_for
from tests.test_dashboard import _render
from tests.test_dashboard_devices import OIL_SENTINEL, _oil_section_cards

SENTENCE = "Over the last 10 days the immersion used about 15 kWh. Running the oil from 12:30 to 13:00."


def _text(**attrs) -> str:
    attributes = {(OIL_SENTINEL, name): value for name, value in attrs.items()}
    return _render(alt_heat_schedule_template(OIL_SENTINEL), lambda entity: "oil", attributes).strip()


class TestTheText:
    def test_it_prints_the_sentence_when_there_is_one(self):
        assert _text(alt_schedule_suggestion=SENTENCE, alt_schedule_days=10) == SENTENCE

    def test_before_a_week_of_data_it_says_it_is_still_learning(self):
        text = _text()
        assert "learning" in text
        assert f"{ALT_HEAT_SCHEDULE_MIN_DAYS} days" in text

    def test_with_a_week_and_nothing_to_suggest_it_says_so_and_the_days(self):
        text = _text(alt_schedule_days=9, alt_schedule=[])
        assert "9 days" in text
        assert "no regular" in text.lower()

    def test_it_never_prints_none(self):
        assert "None" not in _text()
        assert "None" not in _text(alt_schedule_days=9)


class TestTheLabel:
    """The card names the alternative by the sensor's alt_label, so a new label shows at once."""

    def test_the_default_reads_as_it_always_did(self):
        text = _text(alt_schedule_days=9)
        assert text == "No regular oil schedule would save enough yet, from the last 9 days of heating."
        assert _text() == (
            "Still learning when the immersion heats the water at rates above oil. "
            "A suggested oil schedule appears after 7 days."
        )

    def test_the_oil_label_reads_the_same_as_no_label(self):
        assert _text(alt_label="Oil", alt_schedule_days=9) == _text(alt_schedule_days=9)

    @pytest.mark.parametrize(
        ("label", "word"),
        [("Gas", "gas"), ("Heat pump", "heat pump"), ("Heat Pump", "heat pump"), ("LPG", "LPG")],
    )
    def test_a_label_is_lower_case_in_the_sentence_unless_it_is_all_capitals(self, label, word):
        assert f"No regular {word} schedule" in _text(alt_label=label, alt_schedule_days=9)
        assert f"at rates above {word}." in _text(alt_label=label)
        assert f"A suggested {word} schedule appears" in _text(alt_label=label)

    def test_the_sentence_from_the_integration_is_printed_as_it_is(self):
        assert _text(alt_label="Gas", alt_schedule_suggestion=SENTENCE) == SENTENCE

    def test_the_card_follows_the_python_rule_for_every_label(self):
        """The Jinja in the card and label_forms agree on the form inside a sentence."""
        from custom_components.givenergy_inverter_manager.core.alt_heat_label import label_forms

        for label in ("Oil", "Gas", "Heat pump", "Heat Pump", "LPG", "wood", "A"):
            word = label_forms(label).inside
            assert f"No regular {word} schedule" in _text(alt_label=label, alt_schedule_days=9)


class TestTheSection:
    def _markdown(self, **kwargs) -> list[dict]:
        cards = _oil_section_cards(seen_for(switch=True, oil=True, **kwargs))
        return [
            c
            for c in cards
            if c["type"] == "markdown" and "Cheapest source" not in c["content"]
        ]

    def test_the_line_follows_the_live_suggestion(self):
        live, schedule = self._markdown()
        assert f"state_attr('{OIL_SENTINEL}', 'suggestion')" in live["content"]
        assert f"state_attr('{OIL_SENTINEL}', 'alt_schedule_suggestion')" in schedule["content"]

    @pytest.mark.parametrize("switch", [False, True], ids=["no-switch", "switch"])
    @pytest.mark.parametrize("oil", [False, True], ids=["no-oil", "oil"])
    def test_the_line_shows_only_with_an_oil_price_and_the_switch(self, oil, switch):
        cards = _oil_section_cards(seen_for(switch=switch, oil=oil))
        lines = [
            c
            for c in cards
            if c["type"] == "markdown" and "Cheapest source" not in c["content"]
        ]
        assert len(lines) == (2 if oil and switch else 0)
