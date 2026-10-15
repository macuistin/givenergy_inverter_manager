"""The Plan & bill tab shows the bill audit and the bill without solar from the report sensors."""

from __future__ import annotations

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    devices_of,
)

IDS = default_entity_ids()


def _plan(registry: FakeRegistry | None = None) -> dict:
    return next(v for v in dashboard_dict(FULL_CONFIG, registry)["views"] if v["path"] == "plan")


def _section(view: dict, heading: str) -> dict | None:
    return next((s for s in view["sections"] if s["cards"][0].get("heading") == heading), None)


def _without(*keys: str) -> FakeRegistry:
    return FakeRegistry(
        enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"), absent=set(keys)
    )


def test_the_audit_section_has_one_card_for_each_bill_period():
    section = _section(_plan(), "Bill audit")

    cards = [c for c in section["cards"] if c["type"] == "markdown"]
    assert [c["content"] for c in cards] == [
        f"{{{{ state_attr('{IDS['bill_audit']}', 'html') }}}}",
        f"{{{{ state_attr('{IDS['previous_bill_audit']}', 'html') }}}}",
    ]


def test_the_audit_is_the_full_width_of_the_tab():
    assert _section(_plan(), "Bill audit")["column_span"] == 3


def test_the_audit_card_holds_no_figure_so_it_cannot_go_stale():
    for card in _section(_plan(), "Bill audit")["cards"]:
        if card["type"] == "markdown":
            text = card["content"]
            for entity in (IDS["bill_audit"], IDS["previous_bill_audit"]):
                text = text.replace(entity, "")
            assert not any(ch.isdigit() for ch in text)


def test_the_bill_section_shows_the_bill_without_solar_beside_the_projected_bill():
    bill = _section(_plan(), "Bill")
    tiles = [c.get("entity") for c in bill["cards"] if c["type"] == "tile"]

    assert IDS["bill_without_solar"] in tiles
    assert tiles.index(IDS["bill_without_solar"]) == tiles.index(IDS["projected_bill"]) + 1


def test_without_the_previous_audit_sensor_the_section_shows_only_the_current_one():
    section = _section(_plan(_without("previous_bill_audit")), "Bill audit")

    assert len([c for c in section["cards"] if c["type"] == "markdown"]) == 1


def test_without_either_audit_sensor_the_section_is_left_out():
    registry = _without("bill_audit", "previous_bill_audit")

    assert _section(_plan(registry), "Bill audit") is None
