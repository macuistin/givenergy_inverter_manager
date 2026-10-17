"""Where the dashboard states self-sufficiency: a chip on Home energy and the Today sentence."""

from __future__ import annotations

import pytest
import yaml

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    view_cards,
)

IDS = default_entity_ids()
CARD = IDS["self_sufficiency"]


def _view(config: dict, path: str) -> dict:
    return next(v for v in config["views"] if v["path"] == path)


def _section(view: dict, heading: str) -> dict | None:
    for section in view["sections"]:
        if section["cards"][0].get("heading") == heading:
            return section
    return None


def _generated(**registry) -> dict:
    return dashboard_dict(FULL_CONFIG, FakeRegistry(enable_all=True, **registry))


class TestEnergyHeadingChips:
    def _chips(self, config: dict) -> list[str]:
        """The entities of the day's chips. The Settings button beside them has no entity."""
        view = _view(config, "power-flow")
        (heading,) = [c for c in view_cards(view) if c.get("heading") == "Energy"]
        return [badge["entity"] for badge in heading["badges"] if badge["type"] == "entity"]

    def test_self_sufficiency_joins_the_solar_and_the_cost(self):
        assert self._chips(_generated()) == [
            IDS["solar_today"],
            IDS["import_cost_today"],
            IDS["self_sufficiency"],
        ]

    def test_a_chip_is_left_out_when_its_sensor_is_missing(self):
        chips = self._chips(_generated(absent={"self_sufficiency"}))
        assert IDS["self_sufficiency"] not in chips
        assert IDS["solar_today"] in chips


class TestSelfSufficiencyIsShownOnce:
    """Self-sufficiency is stated in the sentence that opens the Today view.

    Home energy keeps a chip in its Energy heading for a glance. The Today view does not repeat
    it as a bar or a tile.
    """

    def _bars(self, config: dict) -> list[str]:
        cards = view_cards(_view(config, "today"))
        return [c["name"] for c in cards if c["type"] == "tile"]

    def _says_it_in_words(self, config: dict) -> bool:
        section = _section(_view(config, "today"), "Today")
        return bool(section) and any(CARD in c.get("content", "") for c in section["cards"])

    def test_the_today_bars_leave_it_out_while_the_sentence_states_it(self):
        config = _generated()
        assert self._says_it_in_words(config)
        assert self._bars(config) == ["Home use from solar", "Solar kept at home"]

    def test_no_tile_of_the_today_tab_repeats_the_figure(self):
        cards = view_cards(_view(_generated(), "today"))
        assert [c for c in cards if c["type"] == "tile" and c["entity"] == CARD] == []

    def test_the_home_energy_chip_stays(self):
        assert CARD in TestEnergyHeadingChips()._chips(_generated())

    @pytest.mark.parametrize("missing", ["import_today", "import_cost_today", "export_today"])
    def test_the_sentence_keeps_it_when_another_total_is_missing(self, missing):
        """Losing another figure must not lose this one."""
        assert self._says_it_in_words(_generated(absent={missing}))

    def test_the_figure_is_gone_from_the_today_tab_when_its_sensor_is_missing(self):
        config = _generated(absent={"self_sufficiency"})
        assert self._bars(config) == ["Home use from solar", "Solar kept at home"]
        assert CARD not in yaml.safe_dump(_view(config, "today"))
