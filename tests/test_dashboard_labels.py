"""The words on the dashboard: what each tile and card says it is."""

from __future__ import annotations

import pytest
import yaml

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    all_cards,
    dashboard_dict,
    dashboard_text,
    default_entity_ids,
    devices_of,
    view_cards,
)
from tests.dashboard_visibility import seen, states_with

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


# ── Battery view ─────────────────────────────────────────────────────────────

def _battery_section(heading: str, *, registry=None) -> list[dict]:
    parsed = yaml.safe_load(dashboard_text(registry=registry))
    view = next(v for v in parsed["views"] if v["path"] == "battery")
    section = next(s for s in view["sections"] if s["cards"][0]["heading"] == heading)
    return section["cards"][1:]


def _battery_seen(heading: str, switch_state: str) -> list[dict]:
    config = dashboard_dict(FULL_CONFIG, ev_brand="myenergi")
    devices = devices_of(FULL_CONFIG, "myenergi")
    states = states_with(devices, {_IDS["charge_target_override_enabled"]: switch_state})
    view = next(v for v in seen(config, states)["views"] if v["path"] == "battery")
    section = next(s for s in view["sections"] if s["cards"][0]["heading"] == heading)
    return section["cards"][1:]


class TestTonightsChargePlan:
    def test_the_plan_sentence_is_the_first_element(self):
        first = _battery_section("Tonight's charge plan")[0]
        assert first["type"] == "markdown"
        assert first["content"] == f"{{{{ states('{_IDS['charge_plan']}') }}}}"

    def test_the_other_tiles_stay_after_it(self):
        names = [c["name"] for c in _battery_section("Tonight's charge plan")[1:]]
        assert names == ["Target tonight", "Est. cost", "At sunrise", "Rate floor"]

    def test_the_section_works_while_the_plan_sensor_is_disabled(self):
        cards = _battery_section("Tonight's charge plan", registry=FakeRegistry())
        assert {c["type"] for c in cards} == {"tile"}
        assert cards[0]["name"] == "Target tonight"


class TestChargeSettingsInForce:
    def _names(self, switch_state: str) -> list[str]:
        return [c.get("name") for c in _battery_seen("Charge settings in force", switch_state)]

    def test_the_override_value_shows_only_while_the_override_is_on(self):
        assert "Target override" in self._names("on")
        assert "Target override" not in self._names("off")

    def test_the_override_switch_always_shows(self):
        assert "Override on" in self._names("on")
        assert "Override on" in self._names("off")

    def test_the_value_is_hidden_by_a_condition_on_the_switch_state(self):
        card = next(
            c
            for c in _battery_section("Charge settings in force")
            if c.get("name") == "Target override"
        )
        assert card["visibility"] == [
            {
                "condition": "state",
                "entity": _IDS["charge_target_override_enabled"],
                "state": "on",
            }
        ]

    def test_dry_run_reads_on_or_off_from_the_summary_attribute(self):
        card = next(
            c for c in _battery_section("Charge settings in force") if c.get("name") == "Dry run"
        )
        assert card["entity"] == _IDS["dry_run_active"]
        assert card["state_content"] == ["summary"]

    def test_the_dry_run_sensor_state_is_unchanged_for_the_banner(self):
        """The banner of a stored dashboard tests the state True, so that stays."""
        settings = yaml.safe_load(dashboard_text())["views"][0]["sections"]
        banner = next(s for s in settings if s["cards"][0]["heading"] == "Dry run is on")
        assert banner["visibility"][0]["state"] == "True"
