"""The Cheapest source card names the alternative by the label the user gave it.

The sensor's state is `electricity`, `solar` or `alternative`, whatever the label is, so that
automations do not change when it does. The dashboard card prints the label in its place.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.dashboard.templates import (
    cheapest_source_template,
)
from tests.test_dashboard import _render
from tests.test_dashboard_devices import OIL_SENTINEL


def _text(state: str, **attrs) -> str:
    attributes = {(OIL_SENTINEL, name): value for name, value in attrs.items()}
    out = _render(cheapest_source_template(OIL_SENTINEL), lambda entity: state, attributes)
    return " ".join(out.split())


@pytest.mark.parametrize("label", ["Oil", "Gas", "Heat pump", "LPG"])
def test_the_alternative_is_named_by_its_label(label):
    assert _text("alternative", alt_label=label) == f"**Cheapest source** {label}"


def test_without_a_label_it_reads_oil_as_it_always_did():
    assert _text("alternative") == "**Cheapest source** Oil"


@pytest.mark.parametrize(
    ("state", "shown"),
    [("electricity", "Electricity"), ("solar", "Solar"), ("unavailable", "Unavailable")],
)
def test_other_states_are_shown_as_they_are_whatever_the_label(state, shown):
    assert _text(state, alt_label="Gas") == f"**Cheapest source** {shown}"


def test_the_section_holds_the_card_not_a_tile_of_the_raw_state():
    from tests.dashboard_visibility import seen_for
    from tests.test_dashboard_devices import _oil_section_cards

    cards = _oil_section_cards(seen_for(switch=True, sensor=True, oil=True))
    assert not [c for c in cards if c["type"] == "tile" and "cheapest" in c.get("entity", "")]
    assert [c for c in cards if "Cheapest source" in c.get("content", "")]
