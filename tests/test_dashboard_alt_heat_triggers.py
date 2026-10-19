"""The alternative heating triggers on Home energy (banner) and Hot water (tiles)."""

from __future__ import annotations

from jinja2 import Environment

from custom_components.givenergy_inverter_manager.core.devices import Device
from tests.dashboard_support import FakeRegistry, dashboard_dict, default_entity_ids
from tests.dashboard_visibility import seen, states_with

IDS = default_entity_ids()
READY_BY = IDS["water_heating_ready_by_trigger"]
LOW_WATER = IDS["water_heating_low_water_trigger"]
BANNER = "Start the alternative heating"
TILE_NAMES = {"Ready-by start", "Low water"}
EVERYTHING = set(Device)


def _view(dashboard: dict, path: str) -> dict:
    return next(v for v in dashboard["views"] if v["path"] == path)


def _headings(view: dict) -> list[str | None]:
    return [s["cards"][0].get("heading") for s in view["sections"]]


def _states(ready_by: str, low_water: str, devices=EVERYTHING) -> dict[str, str]:
    return states_with(devices, {READY_BY: ready_by, LOW_WATER: low_water})


def _tiles(dashboard: dict) -> set[str]:
    found: set[str] = set()

    def walk(card: dict) -> None:
        if card.get("type") == "tile" and card.get("name") in TILE_NAMES:
            found.add(card["name"])
        for child in card.get("cards", []):
            walk(child)

    for section in _view(dashboard, "immersion")["sections"]:
        for card in section["cards"]:
            walk(card)
    return found


def _render(content: str, attrs: dict, states: dict) -> str:
    return Environment().from_string(content).render(
        is_state=lambda entity, state: states.get(entity) == state,
        state_attr=lambda entity, name: attrs.get((entity, name)),
    )


class TestTheBanner:
    def _seen(self, ready_by, low_water, devices=EVERYTHING):
        return _headings(_view(seen(dashboard_dict(), _states(ready_by, low_water, devices)), "power-flow"))

    def test_it_shows_for_the_ready_by_trigger_alone(self):
        assert BANNER in self._seen("start_now", "idle")

    def test_it_shows_for_the_low_water_trigger_alone(self):
        assert BANNER in self._seen("idle", "start_now")

    def test_it_is_hidden_while_both_are_idle(self):
        assert BANNER not in self._seen("idle", "idle")

    def test_it_is_hidden_without_the_alternative_heating(self):
        devices = EVERYTHING - {Device.ALTERNATIVE_HEAT}
        assert BANNER not in self._seen("start_now", "start_now", devices)

    def test_it_sits_after_the_repairs_banner(self):
        headings = _headings(_view(dashboard_dict(), "power-flow"))
        assert headings.index(BANNER) == headings.index("Needs your attention") + 1

    def test_it_uses_only_conditions_the_floor_has(self):
        section = next(
            s for s in _view(dashboard_dict(), "power-flow")["sections"]
            if s["cards"][0].get("heading") == BANNER
        )
        kinds = {c["condition"] for c in section["visibility"]}
        kinds |= {c["condition"] for v in section["visibility"] for c in v.get("conditions", [])}
        assert kinds <= {"state", "numeric_state", "user", "or"}

    def test_there_is_no_banner_when_the_sensors_are_not_registered(self):
        absent = {"water_heating_ready_by_trigger", "water_heating_low_water_trigger"}
        dashboard = dashboard_dict(registry=FakeRegistry(absent=absent))
        # The device is present, but the ids are the expected ones, so the banner still exists
        # and is hidden by the sensors having no state.
        states = states_with(EVERYTHING)
        assert BANNER not in _headings(_view(seen(dashboard, states), "power-flow"))


class TestTheBannerText:
    ATTRS = {
        (READY_BY, "alt_label"): "Heat pump",
        (READY_BY, "run_minutes"): 90,
        (READY_BY, "ready_time"): "07:00",
        (LOW_WATER, "alt_label"): "HP",
    }

    def _text(self, ready_by, low_water):
        from custom_components.givenergy_inverter_manager.dashboard.templates import (
            alt_heat_banner_template,
        )

        return _render(
            alt_heat_banner_template(READY_BY, LOW_WATER),
            self.ATTRS,
            {READY_BY: ready_by, LOW_WATER: low_water},
        )

    def test_the_ready_by_line_names_the_label_in_lower_case_and_the_time(self):
        text = self._text("start_now", "idle")
        assert "heat pump" in text
        assert "for 07:00" in text
        assert "about 90 minutes" in text
        assert "lower limit" not in text

    def test_the_low_water_line_keeps_a_capitalised_label(self):
        text = self._text("idle", "start_now")
        assert "Start the HP now" in text
        assert "lower limit" in text

    def test_both_lines_show_when_both_are_on(self):
        text = self._text("start_now", "start_now")
        assert "on time" in text
        assert "lower limit" in text


class TestTheTiles:
    def test_hot_water_shows_both_tiles_with_the_alternative_heating(self):
        assert _tiles(seen(dashboard_dict(), _states("idle", "idle"))) == TILE_NAMES

    def test_hot_water_shows_neither_without_it(self):
        devices = EVERYTHING - {Device.ALTERNATIVE_HEAT}
        assert _tiles(seen(dashboard_dict(), _states("idle", "idle", devices))) == set()

    def test_each_tile_reads_its_trigger_sensor(self):
        entities = {}
        for section in _view(dashboard_dict(), "immersion")["sections"]:
            stack = list(section["cards"])
            while stack:
                card = stack.pop()
                stack.extend(card.get("cards", []))
                if card.get("name") in TILE_NAMES:
                    entities[card["name"]] = card["entity"]
        assert entities == {"Ready-by start": READY_BY, "Low water": LOW_WATER}
