"""The suggested oil schedule line in the oil section of the Immersion view.

The line is a markdown card that reads attributes of the cheapest source sensor. A Lovelace
condition cannot test for an attribute, so the card itself says when the integration is still
learning or has nothing to suggest. The section's own conditions (an oil price and an immersion
switch) hide the line with it. The suggestion line above it is not changed.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import OIL_SCHEDULE_MIN_DAYS
from custom_components.givenergy_inverter_manager.dashboard.templates import oil_schedule_template
from tests.dashboard_visibility import seen_for
from tests.test_dashboard import _render
from tests.test_dashboard_devices import OIL_SENTINEL, _oil_section_cards

SENTENCE = "Over the last 10 days the immersion used about 15 kWh. Running the oil from 12:30 to 13:00."


def _text(**attrs) -> str:
    attributes = {(OIL_SENTINEL, name): value for name, value in attrs.items()}
    return _render(oil_schedule_template(OIL_SENTINEL), lambda entity: "oil", attributes).strip()


class TestTheText:
    def test_it_prints_the_sentence_when_there_is_one(self):
        assert _text(oil_schedule_suggestion=SENTENCE, oil_schedule_days=10) == SENTENCE

    def test_before_a_week_of_data_it_says_it_is_still_learning(self):
        text = _text()
        assert "learning" in text
        assert f"{OIL_SCHEDULE_MIN_DAYS} days" in text

    def test_with_a_week_and_nothing_to_suggest_it_says_so_and_the_days(self):
        text = _text(oil_schedule_days=9, oil_schedule=[])
        assert "9 days" in text
        assert "no regular" in text.lower()

    def test_it_never_prints_none(self):
        assert "None" not in _text()
        assert "None" not in _text(oil_schedule_days=9)


class TestTheSection:
    def _markdown(self, **kwargs) -> list[dict]:
        cards = _oil_section_cards(seen_for(switch=True, oil=True, **kwargs))
        return [c for c in cards if c["type"] == "markdown"]

    def test_the_line_follows_the_live_suggestion(self):
        live, schedule = self._markdown()
        assert f"state_attr('{OIL_SENTINEL}', 'suggestion')" in live["content"]
        assert f"state_attr('{OIL_SENTINEL}', 'oil_schedule_suggestion')" in schedule["content"]

    @pytest.mark.parametrize("switch", [False, True], ids=["no-switch", "switch"])
    @pytest.mark.parametrize("oil", [False, True], ids=["no-oil", "oil"])
    def test_the_line_shows_only_with_an_oil_price_and_the_switch(self, oil, switch):
        cards = _oil_section_cards(seen_for(switch=switch, oil=oil))
        lines = [c for c in cards if c["type"] == "markdown"]
        assert len(lines) == (2 if oil and switch else 0)
