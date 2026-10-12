"""
The immersion chart for every combination of the switch and the temperature sensor.

The chart is a built-in history graph, so it needs no custom card. It draws the heater's power
as a line beside the temperatures, and a tile above it says whether the heater is on. A switch
with no sensor gets a small chart of the heater alone and its own tile.
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


def _heater_tiles(config: dict) -> list[dict]:
    return [
        c
        for c in view_cards(_immersion(config))
        if c["type"] == "tile" and c["entity"] == IDS["immersion_power"]
    ]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
class TestEveryCombination:
    def _seen(self, combination) -> dict:
        ev, switch, sensor = combination
        return seen_for(ev=ev, switch=switch, sensor=sensor)

    def test_there_is_one_chart_when_there_is_a_sensor_or_a_switch(self, combination):
        _, switch, sensor = combination
        assert len(_charts(self._seen(combination))) == (1 if switch or sensor else 0)

    def test_the_heater_is_a_row_only_with_the_switch(self, combination):
        _, switch, _ = combination
        assert (IDS["immersion_power"] in _plotted(self._seen(combination))) == switch

    def test_the_temperature_is_a_row_only_with_the_sensor(self, combination):
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

    def test_a_heater_tile_is_shown_exactly_with_the_switch(self, combination):
        _, switch, _ = combination
        assert len(_heater_tiles(self._seen(combination))) == (1 if switch else 0)


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


class TestTheHeaterChartWithoutASensor:
    def test_it_holds_the_heater_row_only(self):
        (chart,) = _charts(seen_for(switch=True))
        assert [(r["name"], r["entity"]) for r in chart["entities"]] == [
            ("Heater power", IDS["immersion_power"])
        ]


class TestTheHeaterTile:
    def test_it_sits_in_the_water_section_with_both_devices(self):
        config = seen_for(switch=True, sensor=True)
        cards = view_cards(_immersion(config))
        heading = next(i for i, c in enumerate(cards) if c.get("heading") == "Water temperature")
        tile = _heater_tiles(config)[0]
        assert cards.index(tile) == heading + 1

    def test_it_sits_in_the_heater_section_with_the_switch_alone(self):
        config = seen_for(switch=True)
        cards = view_cards(_immersion(config))
        heading = next(i for i, c in enumerate(cards) if c.get("heading") == "Heater on or off")
        assert cards.index(_heater_tiles(config)[0]) == heading + 1

    def test_it_shows_the_heater_power_and_has_no_controls(self):
        (tile,) = _heater_tiles(seen_for(switch=True))
        assert tile["name"] == "Heater power"
        assert tile["entity"] == IDS["immersion_power"]
        assert "features" not in tile


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


def test_with_apexcharts_card_a_switch_alone_gets_a_heater_band_chart():
    shown = seen_for(resources=[_APEX_URL], switch=True, sensor=False)
    cards = [c for c in view_cards(_immersion(shown)) if c["type"] == "custom:apexcharts-card"]
    assert [s["name"] for card in cards for s in card["series"]] == ["Heater on"]
