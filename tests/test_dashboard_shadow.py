"""The Shadow tariffs sub-view, opened from the Bill & tariff tab, and its link."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import unquote

import jinja2

from tests.core.test_shadow_tariffs import shadow
from tests.dashboard_support import (
    ENTRY_ID,
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    devices_of,
)
from tests.helpers import table_rows

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


def _all_headings(view: dict) -> list[str]:
    return [c.get("heading") for s in view["sections"] for c in s["cards"] if "heading" in c]


def _text(view: dict) -> str:
    return " ".join(card.get("content", "") for s in view["sections"] for card in s["cards"])


def test_without_a_shadow_tariff_there_is_no_view_and_no_link():
    views = _views(_config(), _registry())
    assert "shadow-tariffs" not in views
    assert "Shadow tariffs" not in _all_headings(views["bill"])


def test_the_view_is_a_sub_view_that_returns_to_the_bill_tab():
    views = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))
    view = views["shadow-tariffs"]
    assert (view["subview"], view["back_path"]) == (True, "bill")


def _render(template: str, states: dict[str, str], attributes: dict | None = None) -> str:
    """The template as Home Assistant would print it, with these states and attributes."""
    attributes = attributes or {}
    env = jinja2.Environment(autoescape=False)  # noqa: S701 - markdown, as Home Assistant renders it
    return env.from_string(template).render(
        states=lambda entity: states.get(entity, "unknown"),
        has_value=lambda entity: entity in states,
        state_attr=lambda entity, name: attributes.get(entity, {}).get(name),
        as_datetime=datetime.fromisoformat,
    )


SMART_BILL = "sensor.shadow_tariffs_smart_d_n_p_bill"
SMART_DIFF = "sensor.shadow_tariffs_smart_d_n_p_difference"
FLAT_BILL = "sensor.shadow_tariffs_flat_bill"
FLAT_DIFF = "sensor.shadow_tariffs_flat_difference"
COVERAGE = {
    SMART_BILL: {
        "active_tariff_total": 62.41,
        "data_from": "2026-10-17",
        "days_with_data": 28,
        "days_in_bill_period": 31,
    }
}


def _shadow_view() -> dict:
    return _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))["shadow-tariffs"]


def test_the_bill_tab_says_which_tariff_would_cost_least_and_links_to_the_view():
    views = _views(_config(SMART, FLAT), _registry("smart_d_n_p", "flat"))
    section = next(
        s
        for s in views["bill"]["sections"]
        if s["cards"][0].get("heading") == "This bill, line by line"
    )
    heading, verdict = section["cards"][-2:]
    assert (heading["heading"], heading["heading_style"]) == ("Shadow tariffs", "subtitle")
    assert heading["tap_action"] == {"action": "navigate", "navigation_path": "shadow-tariffs"}
    said = _render(verdict["content"], {SMART_DIFF: "-4.24", FLAT_DIFF: "33.89"})
    assert said.startswith("### Smart D/N/P would have cost €4.24 less so far\n")
    assert "These are not bills." in said


def test_the_answer_names_the_cheapest_shadow_tariff_or_says_yours_is():
    verdict = _shadow_view()["sections"][0]["cards"][1]["content"]
    both_cheaper = _render(verdict, {SMART_DIFF: "-4.24", FLAT_DIFF: "-9.50"})
    none_cheaper = _render(verdict, {SMART_DIFF: "0.00", FLAT_DIFF: "33.89"})
    not_known = _render(verdict, {})
    assert both_cheaper.startswith("### Flat would have cost €9.50 less so far")
    assert none_cheaper.startswith("### Your tariff is the cheapest so far")
    assert not_known.startswith("### Your tariff is the cheapest so far")


def test_every_section_of_the_view_is_one_column_so_the_tariffs_read_side_by_side():
    view = _shadow_view()
    assert _headings(view) == ["Compared with your tariff", "Smart D/N/P", "Flat"]
    assert all("column_span" not in section for section in view["sections"])


def _ranking() -> str:
    return _shadow_view()["sections"][0]["cards"][1]["content"]


def _lines(text: str) -> list[str]:
    """The text of each tariff's line in the ranking, without its bar."""
    plain = re.sub(r"<img[^>]*>", "", text.replace("&nbsp;", " "))
    plain = re.sub(r"</?(b|font)[^>]*>", "", plain).split("These are not bills.")[-1]
    return [" ".join(line.split()) for line in plain.splitlines() if line.strip()]


def _bars(text: str) -> list[str]:
    """The length each bar is drawn to, in the order the bars appear."""
    uris = [unquote(src) for src in re.findall(r'src="([^"]+)"', text)]
    return [re.search(r"<rect width='([\d.]+)'[^>]*rx='1.2'[^>]*fill='#(?!888)", u).group(1) for u in uris]


STATES = {SMART_BILL: "58.17", SMART_DIFF: "-4.24", FLAT_BILL: "96.3", FLAT_DIFF: "33.89"}


def test_the_ranking_lists_every_tariff_from_the_cheapest_with_the_difference_in_words():
    """Less or more, never a bare signed figure, which does not say which tariff is dearer."""
    said = _render(_ranking(), STATES, COVERAGE)
    assert _lines(said) == [
        "Smart D/N/P €58.17 €4.24 less",
        "Your tariff €62.41",
        "Flat €96.30 €33.89 more",
    ]


def test_the_bars_share_one_scale_set_by_the_dearest_tariff():
    assert _bars(_render(_ranking(), STATES, COVERAGE)) == ["60.4", "64.8", "100.0"]


def test_a_tariff_with_no_figure_yet_goes_last_and_says_so():
    said = _render(_ranking(), {SMART_BILL: "58.17", SMART_DIFF: "-4.24"}, COVERAGE)
    assert _lines(said)[-1] == "Flat not known yet"
    same = _render(_ranking(), {**STATES, SMART_DIFF: "0.0"}, COVERAGE)
    assert "the same" in _lines(same)[0] + _lines(same)[1]


def test_the_summary_says_the_figures_are_not_bills_and_from_which_day_they_have_data():
    cards = _shadow_view()["sections"][0]["cards"]
    assert "These are not bills." in cards[1]["content"]
    assert _render(cards[2]["content"], {}, COVERAGE) == (
        "Measured usage starts on 17 Oct 2026: 28 of 31 days of this bill period are recorded. "
        "The figures are complete only when all of them are."
    )
    assert "a day not known yet" in _render(cards[2]["content"], {}, {})


def test_each_tariff_opens_with_its_bill_so_far_and_how_it_compares():
    smart, flat = _shadow_view()["sections"][1:]
    said_smart = _render(smart["cards"][1]["content"], STATES).split("<img")[0]
    said_flat = _render(flat["cards"][1]["content"], STATES).split("<img")[0]
    assert "<b>€58.17</b>" in said_smart and "so far" in said_smart
    assert "€4.24 less than your tariff" in said_smart
    assert "<b>€96.30</b>" in said_flat and "€33.89 more than your tariff" in said_flat


def test_each_tariff_shows_its_day_of_rates_its_band_table_and_its_own_rates_with_the_peak():
    view = _shadow_view()
    smart = view["sections"][1]
    text = _text({"sections": [smart]})
    assert "state_attr('sensor.shadow_tariffs_smart_d_n_p_bill', 'bands_table')" in text
    assert "<summary>Rates and charges</summary>" in text and "<img" in text
    rows = [row[:2] for row in table_rows(text)]
    assert ["Smart Peak", "17:00 to 19:00"] in rows
    assert ["Smart Night", "23:00 to 08:00"] in rows
    assert "Smart Peak" not in _text({"sections": [view["sections"][2]]})


def test_a_tariff_name_cannot_break_out_of_the_template_or_the_table():
    tricky = shadow('Sun "&" <moon>', base_rate=0.30, rate_periods=[])
    view = _views(_config(tricky), _registry("sun_moon"))["shadow-tariffs"]
    diff = "sensor.shadow_tariffs_sun_moon_difference"
    bill = "sensor.shadow_tariffs_sun_moon_bill"
    card = view["sections"][0]["cards"][1]["content"]
    said = _render(card, {bill: "40", diff: "-1"}, {bill: {"active_tariff_total": 41}})
    assert said.startswith('### Sun "&" <moon> would have cost €1.00 less so far')
    assert "Sun &quot;&amp;&quot; &lt;moon&gt;" in said


def test_a_disabled_shadow_entity_leaves_that_tariff_out():
    registry = _registry("smart_d_n_p", "flat", disabled=("flat_bill",))
    view = _views(_config(SMART, FLAT), registry)["shadow-tariffs"]
    assert _headings(view) == ["Compared with your tariff", "Smart D/N/P"]


def test_when_every_shadow_entity_is_missing_the_view_and_the_link_go():
    views = _views(_config(SMART), _registry())
    assert "shadow-tariffs" not in views
    assert "Shadow tariffs" not in _all_headings(views["bill"])
