"""The Hot water view prints the cheapest source as a suggestion, not as the raw state.

The sensor's state is `electricity`, `solar` or `alternative`, whatever the label is, so that
automations do not change when it does. The view prints the sensor's suggestion, which names the
alternative by its label.
"""

from __future__ import annotations

from tests.test_dashboard_devices import OIL_SENTINEL


def test_the_hot_water_view_holds_no_tile_of_the_raw_state():
    """The state is a word for automations, so the view prints the suggestion instead."""
    from tests.dashboard_support import view_cards
    from tests.dashboard_visibility import seen_for

    shown = seen_for(switch=True, sensor=True, oil=True)
    cards = view_cards(next(v for v in shown["views"] if v["path"] == "immersion"))
    assert not [c for c in cards if c["type"] == "tile" and c.get("entity") == OIL_SENTINEL]
    assert [
        c for c in cards if f"state_attr('{OIL_SENTINEL}', 'suggestion')" in c.get("content", "")
    ]
