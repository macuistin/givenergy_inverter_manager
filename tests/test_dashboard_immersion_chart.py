"""
The immersion chart for every combination of the switch and the temperature sensor.

The chart is a built-in history graph, so it needs no custom card. It draws the water
temperature, and with the switch as well the target, the minimum and the heater's power as a
line. A row of figures above it gives the heater's power now. A switch with no sensor has no
chart: its figures and its last week tell its story.
"""

from __future__ import annotations

import itertools

import pytest

from tests.dashboard_support import default_entity_ids, view_cards
from tests.dashboard_visibility import seen_for

IDS = default_entity_ids()
SWITCH_AND_SENSOR = [(False, True, True), (True, True, True)]
COMBINATIONS = list(itertools.product([False, True], repeat=3))
_APEX_URL = "/hacsfiles/apexcharts-card/apexcharts-card.js"


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _immersion(config: dict) -> dict:
    return next(v for v in config["views"] if v["path"] == "immersion")


def _charts(config: dict) -> list[dict]:
    return [c for c in view_cards(_immersion(config)) if c["type"] == "history-graph"]


def _headings(config: dict) -> list[str]:
    return [c["heading"] for c in view_cards(_immersion(config)) if c["type"] == "heading"]


def _plotted(config: dict) -> list[str]:
    return [row["entity"] for chart in _charts(config) for row in chart["entities"]]


def _heater_figures(config: dict) -> list[dict]:
    """The rows of figures that give the heater's power now."""
    return [
        c
        for c in view_cards(_immersion(config))
        if c["type"] == "glance" and IDS["immersion_power"] in [r["entity"] for r in c["entities"]]
    ]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
class TestEveryCombination:
    def _seen(self, combination) -> dict:
        ev, switch, sensor = combination
        return seen_for(ev=ev, switch=switch, sensor=sensor)

    def test_there_is_one_chart_when_there_is_a_sensor(self, combination):
        _, _, sensor = combination
        assert len(_charts(self._seen(combination))) == (1 if sensor else 0)

    def test_the_heater_is_a_row_only_with_the_switch_and_the_sensor(self, combination):
        _, switch, sensor = combination
        assert (IDS["immersion_power"] in _plotted(self._seen(combination))) == (switch and sensor)

    def test_the_temperature_is_a_row_only_with_the_sensor(self, combination):
        _, _, sensor = combination
        assert (IDS["immersion_water_temperature"] in _plotted(self._seen(combination))) == sensor

    def test_the_target_and_minimum_need_both_devices(self, combination):
        _, switch, sensor = combination
        plotted = _plotted(self._seen(combination))
        for key in ("immersion_target_temp", "immersion_min_temp"):
            assert (IDS[key] in plotted) == (switch and sensor), key

    def test_there_is_no_separate_heater_power_chart_or_heading(self, combination):
        """The statistics graphs are the week of heating and its cost, with the switch."""
        _, switch, _ = combination
        config = self._seen(combination)
        assert "Heater power" not in _headings(config)
        weekly = [c for c in view_cards(_immersion(config)) if c["type"] == "statistics-graph"]
        assert [c["title"] for c in weekly] == (["Heated", "Cost"] if switch else [])

    def test_the_hot_water_heading_comes_with_the_sensor_or_the_switch(self, combination):
        _, switch, sensor = combination
        assert ("Hot water" in _headings(self._seen(combination))) == (switch or sensor)

    def test_the_heater_figures_are_shown_exactly_with_the_switch(self, combination):
        _, switch, _ = combination
        assert len(_heater_figures(self._seen(combination))) == (1 if switch else 0)


class TestTheTemperatureChartWithTheHeater:
    @pytest.fixture(params=SWITCH_AND_SENSOR, ids=_label)
    def chart(self, request) -> dict:
        ev, switch, sensor = request.param
        (chart,) = _charts(seen_for(ev=ev, switch=switch, sensor=sensor))
        return chart

    def test_the_rows_are_the_temperatures_then_the_heater(self, chart):
        assert [row["name"] for row in chart["entities"]] == [
            "Water",
            "Target",
            "Minimum",
            "Heater power",
        ]
        assert chart["entities"][-1]["entity"] == IDS["immersion_power"]

    def test_the_chart_spans_12_hours_at_full_width(self, chart):
        assert chart["hours_to_show"] == 12
        assert chart["grid_options"]["columns"] == "full"


class TestTheTemperatureChartWithoutTheHeater:
    def test_it_draws_the_water_only(self):
        (chart,) = _charts(seen_for(sensor=True))
        assert [row["name"] for row in chart["entities"]] == ["Water"]
        assert IDS["immersion_power"] not in str(chart)


class TestTheHeaterFigures:
    def test_they_follow_the_water_sentence_with_both_devices(self):
        config = seen_for(switch=True, sensor=True)
        cards = view_cards(_immersion(config))
        heading = next(i for i, c in enumerate(cards) if c.get("heading") == "Hot water")
        story = cards[heading + 1]
        assert story["type"] == "markdown"
        assert IDS["immersion_water_temperature"] in story["content"]
        assert cards.index(_heater_figures(config)[0]) == heading + 2

    def test_they_follow_why_the_heater_is_on_or_off_with_the_switch_alone(self):
        config = seen_for(switch=True)
        cards = view_cards(_immersion(config))
        heading = next(i for i, c in enumerate(cards) if c.get("heading") == "Hot water")
        reason = IDS["immersion_divert_reason"]
        assert cards[heading + 1]["content"] == (
            f"{{{{ state_attr('{reason}', 'full_text') or states('{reason}') }}}}"
        )
        assert cards.index(_heater_figures(config)[0]) == heading + 2

    def test_they_show_the_heater_power_and_have_no_controls(self):
        (figures,) = _heater_figures(seen_for(switch=True))
        heater = next(r for r in figures["entities"] if r["entity"] == IDS["immersion_power"])
        assert heater["name"] == "Heater"
        assert "features" not in figures


@pytest.mark.parametrize("resources", [None, []], ids=["unknown", "none"])
def test_without_apexcharts_card_the_chart_is_a_history_graph(resources):
    shown = seen_for(resources=resources, switch=True, sensor=True)
    assert _charts(shown) == _charts(seen_for(switch=True, sensor=True))
    assert "apexcharts" not in str(shown)


def test_with_apexcharts_card_one_chart_shades_the_heater_behind_the_water_temperature():
    """The heater is on or off, so one chart shows the temperature and when the heater ran."""
    shown = seen_for(resources=[_APEX_URL], switch=True, sensor=True)
    cards = [c for c in view_cards(_immersion(shown)) if c["type"] == "custom:apexcharts-card"]
    assert len(cards) == 1
    assert not _charts(shown)
    series = {s["name"]: s for s in cards[0]["series"]}
    assert set(series) == {"Water", "Target", "Minimum", "Heater on"}
    heater = series["Heater on"]
    assert heater["entity"] == IDS["immersion_power"]
    assert heater["type"] == "area"
    assert heater["curve"] == "stepline"
    assert heater["transform"] == "return x > 0 ? 1 : 0;"
    assert {a["id"]: a.get("show", True) for a in cards[0]["yaxis"]} == {
        "temp": True,
        "heater": False,
    }


def test_with_apexcharts_card_a_switch_alone_gets_no_chart():
    """With no sensor there is no temperature to draw the heater against."""
    shown = seen_for(resources=[_APEX_URL], switch=True, sensor=False)
    cards = [c for c in view_cards(_immersion(shown)) if c["type"] == "custom:apexcharts-card"]
    assert cards == []
