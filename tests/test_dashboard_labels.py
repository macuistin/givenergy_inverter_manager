"""The words on the dashboard: what each tile and card says it is."""

from __future__ import annotations

import re

import pytest
import yaml

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
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
        assert {path for path, _ in _tiles_of(_IDS["avg_import_rate_this_month"])} == {"plan"}

    def test_the_tariff_table_gives_every_rate_per_kwh(self):
        view = next(v for v in _views() if v["path"] == "tariff")
        tariff = next(s for s in view["sections"] if s["cards"][0]["heading"] == "Tariff in use")
        table = next(c["content"] for c in tariff["cards"] if c["type"] == "markdown")
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
    view = next(v for v in parsed["views"] if v["path"] == "plan")
    section = next(s for s in view["sections"] if s["cards"][0]["heading"] == heading)
    return section["cards"][1:]


def _battery_seen(heading: str, switch_state: str) -> list[dict]:
    config = dashboard_dict(FULL_CONFIG, ev_brand="myenergi")
    devices = devices_of(FULL_CONFIG, "myenergi")
    states = states_with(devices, {_IDS["charge_target_override_enabled"]: switch_state})
    view = next(v for v in seen(config, states)["views"] if v["path"] == "plan")
    section = next(s for s in view["sections"] if s["cards"][0]["heading"] == heading)
    return section["cards"][1:]


class TestTonightsChargePlan:
    def test_the_plan_sentence_is_the_first_element(self):
        first = _battery_section("Tonight's charge")[0]
        assert first["type"] == "markdown"
        assert first["content"] == f"{{{{ states('{_IDS['charge_plan']}') }}}}"

    def test_the_other_tiles_stay_after_it(self):
        names = [c["name"] for c in _battery_section("Tonight's charge")[1:]]
        assert names == [
            "Target",
            "Hold at",
            "Est. cost",
            "Sunrise (no charge)",
            "Sunrise (with charge)",
            "Fixed target",
            "Charge to",
            "Skip tonight",
            "Dry run",
            "Rate floor",
        ]

    def test_the_target_reads_as_held_on_a_skipped_night_and_as_a_goal_otherwise(self):
        tiles = {c["name"]: c for c in _battery_section("Tonight's charge")[1:3]}

        assert tiles["Target"]["visibility"] == [
            {
                "condition": "state",
                "entity": _IDS["overnight_charge_target"],
                "attribute": "plan",
                "state_not": "skip",
            }
        ]
        assert tiles["Hold at"]["visibility"] == [
            {
                "condition": "state",
                "entity": _IDS["overnight_charge_target"],
                "attribute": "plan",
                "state": "skip",
            }
        ]
        assert tiles["Target"]["entity"] == tiles["Hold at"]["entity"]

    def test_the_section_works_while_the_plan_sensor_is_off(self):
        cards = _battery_section(
            "Tonight's charge", registry=FakeRegistry(absent={"charge_plan"})
        )
        assert {c["type"] for c in cards} == {"tile"}
        assert cards[0]["name"] == "Target"


class TestTheTwoSunriseFigures:
    """The estimate at sunrise is shown without and with tonight's planned charge, by name."""

    _NO_CHARGE = "Sunrise (no charge)"
    _WITH_CHARGE = "Sunrise (with charge)"

    @staticmethod
    def _tiles(path: str, *, registry=None) -> dict[str, dict]:
        config = yaml.safe_load(dashboard_text(registry=registry))
        view = next(v for v in config["views"] if v["path"] == path)
        return {c["name"]: c for c in view_cards(view) if c.get("type") == "tile"}

    def test_each_figure_has_a_tile_that_says_which_it_is(self):
        tiles = self._tiles("plan")
        assert tiles[self._NO_CHARGE]["entity"] == _IDS["estimated_soc_at_sunrise"]
        assert tiles[self._WITH_CHARGE]["entity"] == _IDS["estimated_soc_at_sunrise_with_charge"]

    def test_the_names_are_full_width_and_fit_the_tile(self):
        for name in (self._NO_CHARGE, self._WITH_CHARGE):
            tile = self._tiles("plan")[name]
            assert tile["grid_options"]["columns"] == "full"
            assert len(name) <= 22

    def test_the_old_at_sunrise_tile_is_gone(self):
        names = set(self._tiles("plan"))
        assert "At sunrise" not in names

    def test_the_two_tiles_sit_together_in_the_charge_plan(self):
        names = [c["name"] for c in _battery_section("Tonight's charge") if "name" in c]
        assert names[3:5] == [self._NO_CHARGE, self._WITH_CHARGE]

    def test_the_plan_tab_shows_them_once_in_tonights_charge_plan(self):
        """The overnight section beside it explains the outlook and does not repeat them."""
        config = yaml.safe_load(dashboard_text())
        view = next(v for v in config["views"] if v["path"] == "plan")
        names = [c.get("name") for c in view_cards(view)]
        assert names.count(self._NO_CHARGE) == names.count(self._WITH_CHARGE) == 1
        overnight = next(
            s for s in view["sections"] if s["cards"][0].get("heading") == "Battery overnight"
        )
        assert [c["type"] for c in overnight["cards"]][:2] == ["heading", "markdown"]
        assert self._NO_CHARGE not in [c.get("name") for c in overnight["cards"]]

    def test_a_tile_is_left_out_while_its_sensor_is_not_there(self):
        absent = FakeRegistry(absent={"estimated_soc_at_sunrise_with_charge"})
        tiles = self._tiles("plan", registry=absent)
        assert self._WITH_CHARGE not in tiles
        assert self._NO_CHARGE in tiles


class TestChargeSettingsInForce:
    def _names(self, switch_state: str) -> list[str]:
        return [c.get("name") for c in _battery_seen("Tonight's charge", switch_state)]

    def test_the_override_value_shows_only_while_the_override_is_on(self):
        assert "Charge to" in self._names("on")
        assert "Charge to" not in self._names("off")

    def test_the_fixed_target_shows_only_while_it_is_on(self):
        """Tonight's charge lists only what changes it tonight, so an unused switch is hidden."""
        assert "Fixed target" in self._names("on")
        assert "Fixed target" not in self._names("off")

    def test_the_value_is_hidden_by_a_condition_on_the_switch_state(self):
        card = next(
            c
            for c in _battery_section("Tonight's charge")
            if c.get("name") == "Charge to"
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
            c for c in _battery_section("Tonight's charge") if c.get("name") == "Dry run"
        )
        assert card["entity"] == _IDS["dry_run_active"]
        assert card["state_content"] == ["summary"]

    def test_the_dry_run_sensor_state_is_unchanged_for_the_banner(self):
        """The banner of a stored dashboard tests the state True, so that stays."""
        settings = yaml.safe_load(dashboard_text())["views"][0]["sections"]
        banner = next(s for s in settings if s["cards"][0]["heading"] == "Dry run is on")
        assert banner["visibility"][0]["state"] == "True"


# ── Battery overnight ────────────────────────────────────────────────────────


class TestBatteryOvernight:
    """The night survival sensors are read as: does the battery last the night."""

    def _tile(self) -> dict:
        (found,) = [
            c for _, c in _tiles_of(_IDS["night_survival_confidence"]) if c["name"]
        ][:1]
        return found

    def test_the_tile_is_named_for_the_battery_lasting_overnight(self):
        assert self._tile()["name"] == "Battery overnight"

    def test_the_tile_reads_the_summary_phrase_and_the_charge_at_sunrise(self):
        tile = self._tile()
        assert tile["state_content"] == ["summary"]
        assert tile["grid_options"]["columns"] == "full"

    def test_the_tile_opens_the_plan_tab(self):
        assert self._tile()["tap_action"]["navigation_path"] == "plan"

    def test_the_battery_tile_stays_beside_the_rate_and_cost_tiles(self):
        now = next(v for v in _views() if v["path"] == "power-flow")["sections"][0]["cards"]
        by_name = {c["name"]: c for c in now if c["type"] == "tile"}
        assert by_name["Battery"]["grid_options"]["rows"] == 2
        assert by_name["Rate per kWh"]["grid_options"]["columns"] == 6
        assert by_name["Cost today"]["grid_options"]["columns"] == 6

    def test_no_word_on_the_dashboard_says_survival(self):
        text = re.sub(r"(sensor|switch|number)\.[a-z0-9_]+", "", dashboard_text())
        header_free = text[text.index("views:") :]
        assert "survival" not in header_free.lower()

    def test_the_plan_tab_has_a_battery_overnight_heading(self):
        plan = next(v for v in _views() if v["path"] == "plan")
        headings = [c["heading"] for c in view_cards(plan) if c["type"] == "heading"]
        assert "Battery overnight" in headings
