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


def test_the_hot_water_view_holds_no_tile_of_the_raw_state():
    """The state is a word for automations, so the view prints the suggestion instead."""
    from tests.dashboard_support import view_cards
    from tests.dashboard_visibility import seen_for

    shown = seen_for(switch=True, sensor=True, oil=True)
    cards = view_cards(next(v for v in shown["views"] if v["path"] == "immersion"))
    assert not [c for c in cards if c["type"] == "tile" and c.get("entity") == OIL_SENTINEL]
    assert [c for c in cards if f"state_attr('{OIL_SENTINEL}', 'suggestion')" in c.get("content", "")]
