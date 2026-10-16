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


def test_the_three_tables_are_one_column_each_so_they_fill_a_row_on_a_laptop():
    view = _bill()
    for heading in TABLES:
        assert "column_span" not in _section(view, heading), heading
    headings = [s["cards"][0]["heading"] for s in view["sections"]]
    assert headings[-3:] == list(TABLES)


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
