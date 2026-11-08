"""The Shadow tariffs sub-view, opened from the Bill & tariff tab, and its link."""

from __future__ import annotations

from types import SimpleNamespace

from tests.core.test_shadow_tariffs import shadow
from tests.dashboard_support import (
    ENTRY_ID,
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    devices_of,
)

SMART = shadow(
    "Smart D/N/P",
    base_rate=0.35,
    rate_periods=[
        {"name": "Smart Night", "rate": 0.20, "start": "23:00", "end": "08:00"},
        {"name": "Smart Peak", "rate": 0.45, "start": "17:00", "end": "19:00"},
    ],
)
FLAT = shadow("Flat", base_rate=0.30, rate_periods=[])


def _config(*shadows: dict) -> dict:
    return {**FULL_CONFIG, "shadow_tariffs": list(shadows)}


def _registry(*keys: str, disabled: tuple[str, ...] = ()) -> FakeRegistry:
    """The usual registry plus the three entities of each shadow tariff key."""
    registry = FakeRegistry(enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"))
    for key in keys:
        for domain, suffix in (
            ("sensor", "bill"),
            ("sensor", "difference"),
            ("binary_sensor", "cheaper"),
        ):
            uid = f"shadow_{key}_{suffix}"
            entity_id = f"{domain}.shadow_tariffs_{key}_{suffix}"
            registry._by_uid[(domain, f"{ENTRY_ID}_{uid}")] = entity_id
            registry._entries[entity_id] = SimpleNamespace(
                entity_id=entity_id,
                name=None,
                original_name=uid,
                disabled_by="user" if f"{key}_{suffix}" in disabled else None,
            )
    return registry


def _views(config: dict, registry: FakeRegistry) -> dict[str, dict]:
    return {v["path"]: v for v in dashboard_dict(config, registry)["views"]}


def _headings(view: dict) -> list[str]:
    return [s["cards"][0].get("heading") for s in view["sections"]]


def _text(view: dict) -> str:
    return " ".join(card.get("content", "") for s in view["sections"] for card in s["cards"])


def test_without_a_shadow_tariff_there_is_no_view_and_no_link():
    views = _views(_config(), _registry())
    assert "shadow-tariffs" not in views
    assert "Shadow tariffs" not in _headings(views["bill"])


def test_the_view_is_a_sub_view_that_returns_to_the_bill_tab():
    views = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))
    view = views["shadow-tariffs"]
    assert (view["subview"], view["back_path"]) == (True, "bill")


def test_the_bill_tab_links_to_the_view_and_shows_each_difference():
    views = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))
    section = next(
        s for s in views["bill"]["sections"] if s["cards"][0].get("heading") == "Shadow tariffs"
    )
    heading, _, glance = section["cards"]
    assert heading["tap_action"] == {"action": "navigate", "navigation_path": "shadow-tariffs"}
    assert [row["entity"] for row in glance["entities"]] == [
        "sensor.shadow_tariffs_smart_d_n_p_difference",
        "sensor.shadow_tariffs_flat_difference",
    ]


def test_the_view_compares_every_tariff_with_yours_and_says_yes_or_no():
    view = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))["shadow-tariffs"]
    assert _headings(view) == ["Compared with your tariff", "Smart D/N/P", "Flat"]
    summary = _text({"sections": view["sections"][:1]})
    assert "not bills" in summary
    assert "| Smart D/N/P |" in summary and "| Flat |" in summary
    assert "state_attr('sensor.shadow_tariffs_flat_bill', 'would_be_cheaper')" in summary
    assert "state_attr('sensor.shadow_tariffs_smart_d_n_p_bill', 'days_with_data')" in summary


def test_each_tariff_shows_its_band_table_and_its_own_rates_with_the_peak():
    view = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))["shadow-tariffs"]
    smart = view["sections"][1]
    text = _text({"sections": [smart]})
    assert "state_attr('sensor.shadow_tariffs_smart_d_n_p_bill', 'bands_table')" in text
    assert "Smart Peak" in text and "17:00 to 19:00" in text
    assert "Smart Night" in text and "23:00 to 08:00" in text
    assert "Would it have cost less so far?" in text
    assert "Smart Peak" not in _text({"sections": [view["sections"][2]]})


def test_a_disabled_shadow_entity_leaves_that_tariff_out():
    registry = _registry("smart_d_n_p", "flat", disabled=("flat_bill",))
    view = _views(_config(SMART, FLAT), registry)["shadow-tariffs"]
    assert _headings(view) == ["Compared with your tariff", "Smart D/N/P"]


def test_when_every_shadow_entity_is_missing_the_view_and_the_link_go():
    views = _views(_config(SMART), _registry())
    assert "shadow-tariffs" not in views
    assert "Shadow tariffs" not in _headings(views["bill"])
