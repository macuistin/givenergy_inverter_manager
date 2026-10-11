"""
The charts that fill the Bill and Solar and forecast views.

The Bill chart plots the import cost and the export credit of each day from long-term
statistics. The Solar chart plots the solar generated for each of the
last 7 days. The forecast keeps no long-term statistics, so the chart plots what was generated
and the forecast figures sit in the tiles above it. No custom card draws either chart.
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
    return [
        c
        for c in view_cards(_view(config, path))
        if c["type"] in ("statistics-graph", "history-graph")
    ]


def _headings(config: dict, path: str) -> list[str]:
    return [c["heading"] for c in view_cards(_view(config, path)) if c["type"] == "heading"]


def _plotted(chart: dict) -> list[str]:
    return [row["entity"] for row in chart["entities"]]


# ── Bill ─────────────────────────────────────────────────────────────────────


def test_the_bill_view_plots_the_cost_of_each_day():
    (chart,) = _charts(dashboard_dict(), "bill")
    assert chart["type"] == "statistics-graph"
    assert chart["chart_type"] == "bar"
    assert chart["period"] == "day"
    assert chart["stat_types"] == ["change"]
    assert chart["days_to_show"] == 31
    assert chart["entities"] == [
        {"entity": IDS["import_cost_today"], "name": "Import cost"},
        {"entity": IDS["export_earnings_today"], "name": "Export credit"},
    ]


def test_the_bill_chart_says_what_it_plots_and_how_far_back():
    assert "Cost per day, last 31 days" in _headings(dashboard_dict(), "bill")


def test_the_bill_chart_holds_a_whole_bill_period():
    """A bill period is a calendar month at most, so 31 days always holds the one in progress."""
    (chart,) = _charts(dashboard_dict(), "bill")
    assert chart["days_to_show"] >= 31


def test_the_bill_chart_is_taller_than_the_default_graph():
    (chart,) = _charts(dashboard_dict(), "bill")
    assert chart["grid_options"] == {"columns": "full", "rows": 5}


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_bill_chart_is_the_same_for_every_combination_of_devices(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    assert _charts(shown, "bill") == _charts(dashboard_dict(), "bill")


@pytest.mark.parametrize(
    "resources", [None, [], _FLOW_ONLY, [_APEX_URL]], ids=["unknown", "none", "flow-only", "apex"]
)
def test_the_bill_chart_needs_no_custom_card(resources):
    chart = _charts(dashboard_dict(resources=resources), "bill")[0]
    assert chart["type"] == "statistics-graph"


def test_a_cost_sensor_that_is_missing_leaves_its_series_out():
    registry = FakeRegistry(enable_all=True, absent={"export_earnings_today"})
    (chart,) = _charts(dashboard_dict(registry=registry), "bill")
    assert _plotted(chart) == [IDS["import_cost_today"]]


def test_with_no_cost_sensor_there_is_no_chart_and_no_lone_heading():
    registry = FakeRegistry(enable_all=True, absent={"import_cost_today", "export_earnings_today"})
    bill = dashboard_dict(registry=registry)
    assert _charts(bill, "bill") == []
    assert not any(h.startswith("Cost per day") for h in _headings(bill, "bill"))


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
    assert chart["entities"] == [{"entity": IDS["solar_today"], "name": "Generated"}]


def test_the_solar_chart_takes_the_full_width():
    assert _days_chart(dashboard_dict())["grid_options"]["columns"] == "full"


def test_the_solar_view_says_it_is_the_last_7_days():
    assert "Last 7 days" in _headings(dashboard_dict(), "solar")


def test_the_forecast_figures_stay_in_tiles_beside_the_chart():
    shown = {c["entity"] for c in view_cards(_view(dashboard_dict(), "solar")) if c["type"] == "tile"}
    assert {IDS["solar_forecast_raw_today"], IDS["solar_actual_vs_forecast_pct"]} <= shown


@pytest.mark.parametrize("resources", [None, [], _FLOW_ONLY, [_APEX_URL]])
def test_no_custom_chart_is_built_even_when_apexcharts_card_is_installed(resources):
    text = dashboard_text(resources=resources)
    assert "apexcharts" not in text
    assert "custom:apex" not in text


def test_no_history_graph_plots_the_solar_sensors():
    """The generated sensor climbs and resets, so a history graph would draw a sawtooth."""
    for resources in (None, _FLOW_ONLY):
        for chart in _charts(dashboard_dict(resources=resources), "solar"):
            if chart["type"] == "history-graph":
                assert IDS["solar_today"] not in _plotted(chart)


def test_without_a_forecast_sensor_there_is_no_forecast_chart():
    config = dashboard_dict(_NO_FORECAST)
    assert "Last 7 days" not in _headings(config, "solar")
    assert [c["type"] for c in _charts(config, "solar")] == ["statistics-graph"]


def test_a_forecast_sensor_that_is_disabled_leaves_the_chart_out():
    registry = FakeRegistry(enable_all=True, absent={"solar_forecast_raw_today"})
    config = dashboard_dict(registry=registry)
    assert "Last 7 days" not in _headings(config, "solar")
    assert [c["type"] for c in _charts(config, "solar")] == ["statistics-graph"]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_solar_charts_are_the_same_for_every_combination_of_devices(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    assert _charts(shown, "solar") == _charts(dashboard_dict(), "solar")


def test_the_dashboard_serialises_to_valid_yaml_with_both_charts():
    parsed = yaml.safe_load(dashboard_text())
    assert _charts(parsed, "bill") and _charts(parsed, "solar")
