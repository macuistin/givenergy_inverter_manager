"""The words on the dashboard: what each tile and card says it is."""

from __future__ import annotations

import pytest
import yaml

from tests.dashboard_support import all_cards, dashboard_text, default_entity_ids, view_cards

_IDS = default_entity_ids()
# The sensors whose state is an amount of money for one kWh. Their unit stays the bare
# currency, because it feeds long-term statistics, so the dashboard names the kWh.
_RATE_KEYS = ("current_rate", "avg_import_rate_this_month")


def _views() -> list[dict]:
    return yaml.safe_load(dashboard_text())["views"]


def _tiles_of(entity: str) -> list[tuple[str, dict]]:
    return [
        (view["path"], card)
        for view in _views()
        for card in view_cards(view)
        if card.get("type") == "tile" and card.get("entity") == entity
    ]


class TestRatesSayPerKwh:
    @pytest.mark.parametrize("key", _RATE_KEYS)
    def test_every_tile_of_a_rate_names_the_kwh(self, key):
        tiles = _tiles_of(_IDS[key])
        assert tiles, key
        assert all("kWh" in card["name"] for _, card in tiles), tiles

    def test_the_current_rate_is_labelled_on_power_flow_and_today(self):
        assert {path for path, _ in _tiles_of(_IDS["current_rate"])} == {"power-flow", "today"}

    def test_the_average_rate_is_labelled_on_bill(self):
        assert {path for path, _ in _tiles_of(_IDS["avg_import_rate_this_month"])} == {"bill"}

    def test_the_tariff_table_gives_every_rate_per_kwh(self):
        tariff = next(v for v in _views() if v["path"] == "tariff")
        table = next(c["content"] for c in all_cards([tariff]) if c["type"] == "markdown")
        header = table.splitlines()[0]
        assert "Rate per kWh" in header
        assert "Billed per kWh" in header
        assert "| Export rate |" in table and "per kWh |" in table

    def test_a_rate_tile_name_fits_a_half_width_tile(self):
        for key in _RATE_KEYS:
            for _, card in _tiles_of(_IDS[key]):
                assert len(card["name"]) <= 15, card["name"]
