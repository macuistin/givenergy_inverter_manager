"""
The charts that fill the Bill & tariff and Today views.

The Bill & tariff view plots what each day cost beside what it would have cost with no solar or
battery, and the cost of each day split by what used it, from long-term statistics. The Today
view plots the solar generated for each of the last 7 days. The forecast keeps no long-term
statistics, so the chart plots what was generated and the forecast figures sit beside it. No
custom card draws either chart.
"""

from __future__ import annotations

import itertools

import pytest
import yaml

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY
from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    dashboard_text,
    default_entity_ids,
    view_cards,
)
from tests.dashboard_visibility import seen_for

IDS = default_entity_ids()
COMBINATIONS = list(itertools.product([False, True], repeat=3))
_APEX_URL = "/hacsfiles/apexcharts-card/apexcharts-card.js"
_FLOW_ONLY = ["/hacsfiles/power-flow-card-plus/power-flow-card-plus.js"]
_NO_FORECAST = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _view(config: dict, path: str) -> dict:
    return next(v for v in config["views"] if v["path"] == path)


def _charts(config: dict, path: str) -> list[dict]:
    """The charts of a view. "solar" names the charts of solar on the Today view."""
    if path == "solar":
        cards = [
            c for c in view_cards(_view(config, "today")) if IDS["solar_today"] in str(c.get("entities"))
        ]
    else:
        cards = view_cards(_view(config, path))
    return [c for c in cards if c["type"] in ("statistics-graph", "history-graph")]


def _paid_chart(config: dict) -> list[dict]:
    """The chart of what each day cost beside what it would have cost."""
    return [c for c in _charts(config, "bill") if IDS["import_cost_today"] in str(c["entities"])]


def _by_use_charts(config: dict) -> list[dict]:
    return [c for c in _charts(config, "bill") if IDS["house_cost_today"] in str(c["entities"])]


def _headings(config: dict, path: str) -> list[str]:
    return [c["heading"] for c in view_cards(_view(config, path)) if c["type"] == "heading"]


def _plotted(chart: dict) -> list[str]:
    return [row["entity"] for row in chart["entities"]]


# ── Bill ─────────────────────────────────────────────────────────────────────

_PAID_HEADING = "Each day: what you paid and would have paid"
_BY_USE_HEADING = "Cost per day by use, last 31 days"


def test_the_bill_view_plots_the_cost_of_each_day_beside_the_cost_without_solar():
    (chart,) = _paid_chart(dashboard_dict())
    assert chart["type"] == "statistics-graph"
    assert chart["chart_type"] == "bar"
    assert chart["period"] == "day"
    assert chart["stat_types"] == ["change"]
    assert chart["days_to_show"] == 14
    assert chart["entities"] == [
        {"entity": IDS["import_cost_today"], "name": "You paid"},
        {"entity": IDS["cost_without_solar_today"], "name": "Would have paid"},
    ]
    assert chart["hide_legend"] is False


def test_the_paid_chart_compares_two_energy_costs_of_the_same_day():
    """The bill without solar adds the standing charge and levy and resets each bill period.

    Beside the import cost of a day it made a day with solar look dearer than without.
    """
    (chart,) = _paid_chart(dashboard_dict())
    assert IDS["bill_without_solar"] not in _plotted(chart)


def test_the_bill_charts_say_what_they_plot_and_how_far_back():
    headings = _headings(dashboard_dict(), "bill")
    assert _PAID_HEADING in headings
    assert _BY_USE_HEADING in headings


def test_the_cost_by_use_holds_a_whole_bill_period():
    """A bill period is a calendar month at most, so 31 days always holds the one in progress."""
    charts = _by_use_charts(seen_for(ev=True, switch=True, sensor=True))
    assert charts
    for chart in charts:
        assert chart["days_to_show"] >= 31
        assert chart["chart_type"] == "bar-stack"


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_paid_chart_is_the_same_for_every_combination_of_devices(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    assert _paid_chart(shown) == _paid_chart(dashboard_dict())


@pytest.mark.parametrize(
    "resources", [None, [], _FLOW_ONLY, [_APEX_URL]], ids=["unknown", "none", "flow-only", "apex"]
)
def test_the_bill_charts_need_no_custom_card(resources):
    charts = _charts(dashboard_dict(resources=resources), "bill")
    assert charts
    assert {chart["type"] for chart in charts} <= {"statistics-graph", "history-graph"}


def test_a_cost_sensor_that_is_missing_leaves_its_series_out():
    registry = FakeRegistry(enable_all=True, absent={"cost_without_solar_today"})
    (chart,) = _paid_chart(dashboard_dict(registry=registry))
    assert _plotted(chart) == [IDS["import_cost_today"]]


def test_with_no_cost_sensor_there_is_no_chart_and_no_lone_heading():
    registry = FakeRegistry(
        enable_all=True, absent={"import_cost_today", "cost_without_solar_today"}
    )
    bill = dashboard_dict(registry=registry)
    assert _paid_chart(bill) == []
    assert _PAID_HEADING not in _headings(bill, "bill")


# ── Solar and forecast ───────────────────────────────────────────────────────


def _days_chart(config: dict) -> dict:
    (chart,) = [c for c in _charts(config, "solar") if c["type"] == "statistics-graph" and c["period"] == "day"]
    return chart


@pytest.mark.parametrize(
    "resources", [None, [], _FLOW_ONLY, [_APEX_URL]], ids=["unknown", "none", "flow-only", "apex"]
)
def test_the_solar_view_plots_what_was_generated_for_7_days(resources):
    chart = _days_chart(dashboard_dict(resources=resources))
    assert chart["type"] == "statistics-graph"
    assert chart["period"] == "day"
    assert chart["days_to_show"] == 7
    assert chart["stat_types"] == ["change"]
    assert chart["entities"] == [{"entity": IDS["solar_today"], "name": "Solar"}]


def test_the_solar_chart_takes_the_full_width():
    assert _days_chart(dashboard_dict())["grid_options"]["columns"] == "full"


def test_the_solar_view_says_it_is_the_last_7_days():
    assert "Solar, last 7 days" in _headings(dashboard_dict(), "today")


def test_the_forecast_figures_sit_beside_the_chart():
    cards = view_cards(_view(dashboard_dict(), "today"))
    shown = {r["entity"] for c in cards if c["type"] == "glance" for r in c["entities"]}
    assert {IDS["solar_forecast_raw_today"], IDS["solar_actual_vs_forecast_pct"]} <= shown


@pytest.mark.parametrize("resources", [None, [], _FLOW_ONLY, [_APEX_URL]])
def test_only_the_immersion_chart_can_use_apexcharts_card(resources):
    """The Bill and Solar charts are core cards. The immersion chart may use apexcharts-card,
    and tomorrow's curve only with a half-hourly forecast, which this install has not."""
    for view in dashboard_dict(resources=resources)["views"]:
        if view["path"] != "immersion":
            assert "apexcharts" not in str(view), view["path"]


def test_no_history_graph_plots_the_solar_sensors():
    """The generated sensor climbs and resets, so a history graph would draw a sawtooth."""
    for resources in (None, _FLOW_ONLY):
        for chart in _charts(dashboard_dict(resources=resources), "solar"):
            if chart["type"] == "history-graph":
                assert IDS["solar_today"] not in _plotted(chart)


def test_without_a_forecast_sensor_the_week_shows_and_the_forecast_does_not():
    config = dashboard_dict(_NO_FORECAST)
    assert "Solar, last 7 days" in _headings(config, "today")
    assert "Forecast" not in _headings(config, "today")
    assert [c["type"] for c in _charts(config, "solar")] == ["statistics-graph"] * 2


def test_a_forecast_sensor_that_is_disabled_leaves_its_figure_out():
    registry = FakeRegistry(enable_all=True, absent={"solar_forecast_raw_today"})
    config = dashboard_dict(registry=registry)
    cards = view_cards(_view(config, "today"))
    shown = {r["entity"] for c in cards if c["type"] == "glance" for r in c["entities"]}
    assert IDS["solar_forecast_raw_today"] not in shown
    assert IDS["solar_actual_vs_forecast_pct"] in shown
    assert [c["type"] for c in _charts(config, "solar")] == ["statistics-graph"] * 2


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_solar_charts_are_the_same_for_every_combination_of_devices(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    assert _charts(shown, "solar") == _charts(dashboard_dict(), "solar")


def test_the_dashboard_serialises_to_valid_yaml_with_both_charts():
    parsed = yaml.safe_load(dashboard_text())
    assert _paid_chart(parsed) and _charts(parsed, "solar")
