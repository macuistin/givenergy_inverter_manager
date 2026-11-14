"""The Cheapest plans section under the bill: where the tariff ranks among the store's plans."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.dashboard.templates import plan_ranking_template
from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    devices_of,
)
from tests.test_dashboard_shadow import _render

RANK = "sensor.tariff_rank"
RANKING = {
    "summary": (
        "Your plan is number 3 of the 40 compared, in the top 3. "
        "The last bill would have been cheapest on Cheap, 4.50 less."
    ),
    "saving_with_cheapest": 4.5,
    "plans_compared": 40,
    "window_start": "2026-09-16",
    "window_end": "2026-10-15",
    "days_with_data": 28,
    "days_priced": 30,
    "ranking": [
        {"rank": 1, "name": "Cheap <b>Plan</b>", "bill": 50.0, "yours": False},
        {"rank": 3, "name": "Your plan", "bill": 54.5, "yours": True},
    ],
}


def _bill(registry: FakeRegistry | None = None) -> dict:
    views = dashboard_dict(FULL_CONFIG, registry)["views"]
    return next(v for v in views if v["path"] == "bill")


def _cards(view: dict) -> list[dict]:
    return [c for s in view["sections"] for c in s["cards"]]


def test_the_section_says_where_you_stand_and_what_the_cheapest_would_save() -> None:
    text = _render(plan_ranking_template(RANK, "€"), {}, {RANK: RANKING})
    assert "Your plan is number 3 of the 40 compared" in text
    assert "The last bill would have been cheapest on Cheap, 4.50 less." in text
    assert "<b>Plan</b>" not in text  # a plan name cannot add markup
    assert "€50.00" in text and "€54.50" in text
    assert "28 of 30 days recorded" in text
    assert "not a bill" in text


def test_a_bar_is_scaled_to_the_dearest_plan_listed() -> None:
    text = _render(plan_ranking_template(RANK, "€"), {}, {RANK: RANKING})
    assert text.count("<img") == 2
    assert "rect width='100'" in text and "rect width='91.7'" in text


def test_before_the_first_comparison_it_says_when_it_runs() -> None:
    text = _render(plan_ranking_template(RANK, "€"), {}, {})
    assert "once a day" in text and "<img" not in text


def test_the_bill_tab_shows_the_section_under_the_bill() -> None:
    cards = _cards(_bill())
    headings = [c.get("heading") for c in cards]
    assert "Cheapest plans" in headings
    ids = default_entity_ids()
    following = cards[headings.index("Cheapest plans") + 1]
    assert ids["plan_rank"] in following["content"]


def test_the_section_is_left_out_when_the_sensor_is_disabled() -> None:
    registry = FakeRegistry(
        enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"), absent={"plan_rank"}
    )
    headings = [c.get("heading") for c in _cards(_bill(registry))]
    assert "Cheapest plans" not in headings
