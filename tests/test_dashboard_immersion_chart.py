"""
The immersion chart for every combination of the switch and the temperature sensor.

The heater's power is a fixed number, so the dashboard shows only whether it is on: a pale band
on the water temperature chart. A switch with no sensor gets a small chart of the band alone.
There is no separate heater power chart.
"""

from __future__ import annotations

import itertools

import pytest

from tests.dashboard_support import default_entity_ids, view_cards
from tests.dashboard_visibility import generated_for, seen_for

IDS = default_entity_ids()
SWITCH_AND_SENSOR = [(False, True, True), (True, True, True)]
COMBINATIONS = list(itertools.product([False, True], repeat=3))
APEX = "custom:apexcharts-card"
_NO_APEX = ["/hacsfiles/power-flow-card-plus/power-flow-card-plus.js"]

HEATER_SERIES = {
    "entity": IDS["immersion_power"],
    "name": "Heater on",
    "type": "area",
    "curve": "stepline",
    "color": "#ff8a80",
    "opacity": 0.15,
    "stroke_width": 0,
    "yaxis_id": "heater",
    "transform": "return x > 0 ? 1 : 0;",
    "show": {"in_header": False, "legend_value": False},
}
TEMP_AXIS = {"id": "temp", "decimals": 0}
HEATER_AXIS = {"id": "heater", "min": 0, "max": 1, "decimals": 0, "show": False}


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _immersion(config: dict) -> dict:
    return next(v for v in config["views"] if v["path"] == "immersion")


def _charts(config: dict) -> list[dict]:
    return [c for c in view_cards(_immersion(config)) if c["type"] == APEX]


def _headings(config: dict) -> list[str]:
    return [c["heading"] for c in view_cards(_immersion(config)) if c["type"] == "heading"]


def _plotted(config: dict) -> list[str]:
    return [s["entity"] for chart in _charts(config) for s in chart["series"]]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
class TestEveryCombination:
    def _seen(self, combination) -> dict:
        ev, switch, sensor = combination
        return seen_for(ev=ev, switch=switch, sensor=sensor)

    def test_there_is_one_chart_when_there_is_a_sensor_or_a_switch(self, combination):
        _, switch, sensor = combination
        assert len(_charts(self._seen(combination))) == (1 if switch or sensor else 0)

    def test_the_heater_is_a_series_only_with_the_switch(self, combination):
        _, switch, _ = combination
        assert (IDS["immersion_power"] in _plotted(self._seen(combination))) == switch

    def test_the_temperature_is_a_series_only_with_the_sensor(self, combination):
        _, _, sensor = combination
        assert (IDS["immersion_water_temperature"] in _plotted(self._seen(combination))) == sensor

    def test_the_target_and_minimum_need_both_devices(self, combination):
        _, switch, sensor = combination
        plotted = _plotted(self._seen(combination))
        for key in ("immersion_target_temp", "immersion_min_temp"):
            assert (IDS[key] in plotted) == (switch and sensor), key

    def test_there_is_no_separate_heater_power_chart_or_heading(self, combination):
        config = self._seen(combination)
        assert "Heater power" not in _headings(config)
        assert not [c for c in view_cards(_immersion(config)) if c["type"] == "statistics-graph"]

    def test_the_switch_alone_gets_a_small_heater_chart_with_its_own_heading(self, combination):
        _, switch, sensor = combination
        assert ("Heater on or off" in _headings(self._seen(combination))) == (switch and not sensor)

    def test_the_water_heading_comes_with_the_sensor(self, combination):
        _, _, sensor = combination
        assert ("Water temperature" in _headings(self._seen(combination))) == sensor


class TestTheTemperatureChartWithTheHeater:
    @pytest.fixture(params=SWITCH_AND_SENSOR, ids=_label)
    def chart(self, request) -> dict:
        ev, switch, sensor = request.param
        (chart,) = _charts(seen_for(ev=ev, switch=switch, sensor=sensor))
        return chart

    def test_the_series_are_the_temperatures_then_the_heater(self, chart):
        assert [s["name"] for s in chart["series"]] == ["Water", "Target", "Minimum", "Heater on"]

    def test_the_heater_series_is_exactly_the_pale_stepped_band(self, chart):
        assert chart["series"][-1] == HEATER_SERIES

    def test_every_temperature_series_is_smooth_on_the_temperature_axis(self, chart):
        temperatures = chart["series"][:-1]
        assert {s["curve"] for s in temperatures} == {"smooth"}
        assert {s["yaxis_id"] for s in temperatures} == {"temp"}

    def test_each_series_sets_its_own_line_width(self, chart):
        widths = {s["name"]: s["stroke_width"] for s in chart["series"]}
        assert widths == {"Water": 2, "Target": 1, "Minimum": 1, "Heater on": 0}

    def test_the_axes_are_the_temperature_and_the_hidden_on_off_axis(self, chart):
        assert chart["yaxis"] == [TEMP_AXIS, HEATER_AXIS]

    def test_the_chart_spans_12_hours_with_no_header_at_full_width(self, chart):
        assert chart["graph_span"] == "12h"
        assert chart["header"] == {"show": False}
        assert chart["grid_options"] == {"columns": "full"}


class TestTheTemperatureChartWithoutTheHeater:
    @pytest.fixture
    def chart(self) -> dict:
        (chart,) = _charts(seen_for(sensor=True))
        return chart

    def test_it_draws_the_water_only(self, chart):
        assert [s["name"] for s in chart["series"]] == ["Water"]
        assert chart["series"][0]["yaxis_id"] == "temp"
        assert chart["series"][0]["curve"] == "smooth"

    def test_it_has_no_heater_axis_and_no_heater_entity(self, chart):
        assert chart["yaxis"] == [TEMP_AXIS]
        assert IDS["immersion_power"] not in str(chart)


class TestTheHeaterChartWithoutASensor:
    @pytest.fixture
    def chart(self) -> dict:
        (chart,) = _charts(seen_for(switch=True))
        return chart

    def test_it_holds_the_on_off_band_only(self, chart):
        assert chart["series"] == [HEATER_SERIES]
        assert chart["yaxis"] == [HEATER_AXIS]


class TestNoGlobalStroke:
    """A global stroke curve or width overrides each series' own, so the band would ramp or show a line."""

    def test_no_generated_apex_chart_sets_apex_config_stroke(self):
        charts = [
            card
            for ev, switch, sensor in COMBINATIONS
            for view in generated_for(ev=ev, switch=switch, sensor=sensor)["views"]
            for card in view_cards(view)
            if card["type"] == APEX
        ]
        assert charts
        for chart in charts:
            assert "stroke" not in chart["apex_config"]

    def test_apex_config_stroke_has_neither_curve_nor_width(self):
        config = generated_for(ev=True, switch=True, sensor=True)
        charts = [c for v in config["views"] for c in view_cards(v) if c["type"] == APEX]
        assert charts
        for chart in charts:
            stroke = chart["apex_config"].get("stroke", {})
            assert "curve" not in stroke
            assert "width" not in stroke


class TestWithoutApexchartsCard:
    """The built-in history graph draws the heater's power as a line, not as a band."""

    @staticmethod
    def _graphs(**devices) -> list[dict]:
        config = seen_for(resources=_NO_APEX, **devices)
        return [c for c in view_cards(_immersion(config)) if c["type"] == "history-graph"]

    @staticmethod
    def _rows(graph: dict) -> list[tuple[str, str]]:
        return [(r["name"], r["entity"]) for r in graph["entities"]]

    def test_a_sensor_and_a_switch_give_one_graph_with_the_heater_row(self):
        (graph,) = self._graphs(switch=True, sensor=True)
        rows = self._rows(graph)
        assert [name for name, _ in rows] == ["Water", "Target", "Minimum", "Heater power"]
        assert rows[-1][1] == IDS["immersion_power"]

    def test_a_sensor_alone_gives_the_water_row_only(self):
        (graph,) = self._graphs(sensor=True)
        assert [name for name, _ in self._rows(graph)] == ["Water"]

    def test_a_switch_alone_gives_the_heater_row_only(self):
        (graph,) = self._graphs(switch=True)
        assert [name for name, _ in self._rows(graph)] == ["Heater power"]

    def test_no_device_gives_no_graph(self):
        assert self._graphs() == []

    def test_no_energy_statistics_graph_is_left(self):
        config = seen_for(resources=_NO_APEX, switch=True, sensor=True)
        assert not [c for c in view_cards(_immersion(config)) if c["type"] == "statistics-graph"]
