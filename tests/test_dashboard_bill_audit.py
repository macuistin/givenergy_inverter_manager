"""The Bill & tariff view shows the bill tables and the bill without solar from the report sensors."""

from __future__ import annotations

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    devices_of,
)

IDS = default_entity_ids()
TABLES = ("This bill, line by line", "Each day", "Last bill")


def _bill(registry: FakeRegistry | None = None) -> dict:
    return next(v for v in dashboard_dict(FULL_CONFIG, registry)["views"] if v["path"] == "bill")


def _section(view: dict, heading: str) -> dict | None:
    return next((s for s in view["sections"] if s["cards"][0].get("heading") == heading), None)


def _without(*keys: str) -> FakeRegistry:
    return FakeRegistry(
        enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"), absent=set(keys)
    )


def _table(view: dict, heading: str) -> str:
    (card,) = [c for c in _section(view, heading)["cards"] if c["type"] == "markdown"]
    return card["content"]


def test_each_table_reads_its_attribute_of_the_audit_sensors():
    view = _bill()
    assert [_table(view, heading) for heading in TABLES] == [
        f"{{{{ state_attr('{IDS['bill_audit']}', 'bill_table') }}}}",
        f"{{{{ state_attr('{IDS['bill_audit']}', 'days_table') }}}}",
        f"{{{{ state_attr('{IDS['previous_bill_audit']}', 'summary_table') }}}}",
    ]


def test_a_wide_section_is_followed_by_a_one_column_one_three_times():
    """Each pair shares a row on a laptop, and no row is left half empty on a tablet."""
    view = _bill()
    layout = [(s["cards"][0]["heading"], s.get("column_span", 1)) for s in view["sections"]]
    assert layout == [
        ("This bill period", 2),
        ("This bill, line by line", 1),
        ("Import and export", 2),
        ("Tariff", 1),
        ("Each day", 2),
        ("Last bill", 1),
    ]


def test_the_period_shows_four_figures_as_tiles_two_to_a_row_on_a_phone():
    """Six of a section's twelve columns: two to a row on a phone, four where it is two wide."""
    tiles = [c for c in _section(_bill(), "This bill period")["cards"] if c["type"] == "tile"]
    assert [(t["name"], t["entity"]) for t in tiles] == [
        ("So far", IDS["accrued_bill"]),
        ("Heading for", IDS["projected_bill"]),
        ("Without solar", IDS["bill_without_solar"]),
        ("Days left", IDS["days_remaining_in_period"]),
    ]
    assert {t["grid_options"]["columns"] for t in tiles} == {6}


def test_a_missing_figure_leaves_its_tile_out():
    period = _section(_bill(_without("projected_bill")), "This bill period")
    assert [c["name"] for c in period["cards"] if c["type"] == "tile"] == [
        "So far",
        "Without solar",
        "Days left",
    ]


def test_the_period_holds_one_chart_and_the_cost_by_use_sits_with_import_and_export():
    view = _bill()
    charts = [c for c in _section(view, "This bill period")["cards"] if "graph" in c["type"]]
    assert [[row["name"] for row in c["entities"]] for c in charts] == [
        ["You paid", "Would have paid"]
    ]
    by_use = _section(view, "Import and export")["cards"]
    assert [c["type"] for c in by_use[:3]] == ["heading", "glance", "heading"]
    assert {c["type"] for c in by_use[3:]} == {"statistics-graph"}
    assert all(c["chart_type"] == "bar-stack" for c in by_use[3:])
    assert [row["name"] for row in by_use[1]["entities"]] == [
        "Import cost",
        "Export credit",
        "Avg per kWh",
    ]


def test_the_table_cards_hold_no_figure_so_they_cannot_go_stale():
    view = _bill()
    for heading in TABLES:
        text = _table(view, heading)
        for entity in (IDS["bill_audit"], IDS["previous_bill_audit"]):
            text = text.replace(entity, "")
        assert not any(ch.isdigit() for ch in text), heading


def test_the_bill_period_opens_with_the_saving_against_the_bill_without_solar():
    period = _section(_bill(), "This bill period")
    saved = period["cards"][1]
    assert saved["type"] == "markdown"
    assert f"states('{IDS['accrued_bill']}')" in saved["content"]
    assert f"states('{IDS['bill_without_solar']}')" in saved["content"]
    assert saved["content"].startswith("{% set paid") and "### Saved" in saved["content"]


def test_without_the_previous_audit_sensor_the_last_bill_is_left_out():
    view = _bill(_without("previous_bill_audit"))
    assert _section(view, "Last bill") is None
    assert _section(view, "This bill, line by line") is not None
    assert _section(view, "Each day") is not None


def test_without_either_audit_sensor_the_tables_are_left_out():
    view = _bill(_without("bill_audit", "previous_bill_audit"))
    for heading in TABLES:
        assert _section(view, heading) is None, heading
