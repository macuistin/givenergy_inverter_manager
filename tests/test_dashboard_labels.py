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


def _figures_of(entity: str) -> list[tuple[str, dict]]:
    """Every named place the entity is shown: its tiles and its rows of a row of figures."""
    rows = [
        (view["path"], row)
        for view in _views()
        for card in view_cards(view)
        if card.get("type") == "glance"
        for row in card["entities"]
        if row["entity"] == entity
    ]
    return _tiles_of(entity) + rows


class TestRatesSayPerKwh:
    def test_every_figure_of_the_average_rate_names_the_kwh(self):
        figures = _figures_of(_IDS["avg_import_rate_this_month"])
        assert figures
        assert all("kWh" in card["name"] for _, card in figures), figures

    def test_the_current_rate_is_a_chip_on_home_energy_only(self):
        """The chip shows the rate with its currency beside the battery and the cheap rate."""
        assert _figures_of(_IDS["current_rate"]) == []
        chips = [
            (view["path"], badge.get("entity"))
            for view in _views()
            for card in view_cards(view)
            for badge in card.get("badges", [])
        ]
        assert [path for path, entity in chips if entity == _IDS["current_rate"]] == ["power-flow"]

    def test_the_average_rate_is_labelled_on_bill(self):
        assert {path for path, _ in _figures_of(_IDS["avg_import_rate_this_month"])} == {"bill"}

    def test_the_tariff_table_gives_every_rate_per_kwh(self):
        """The table the view builds itself, which it does when the Tariff in use sensor is off."""
        registry = FakeRegistry(
            enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"), absent={"tariff_in_use"}
        )
        views = yaml.safe_load(dashboard_text(FULL_CONFIG, registry))["views"]
        view = next(v for v in views if v["path"] == "bill")
        tariff = next(s for s in view["sections"] if s["cards"][0]["heading"] == "Tariff")
        table = next(c["content"] for c in tariff["cards"] if c["type"] == "markdown")
        header = table.splitlines()[0]
        assert "Rate per kWh" in header
        assert "Billed per kWh" in header
        assert "| Export rate |" in table and "per kWh |" in table

    def test_a_rate_tile_name_fits_a_half_width_tile(self):
        for key in _RATE_KEYS:
            for _, card in _tiles_of(_IDS[key]):
                assert len(card["name"]) <= 15, card["name"]


# ── Tonight view ─────────────────────────────────────────────────────────────

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


def _figure_names(cards: list[dict]) -> list[str]:
    return [r["name"] for c in cards if c["type"] == "glance" for r in c["entities"]]


class TestTonightsChargePlan:
    def test_the_headline_is_the_first_element_with_the_plan_sentence_under_it(self):
        first = _battery_section("Tonight")[0]
        assert first["type"] == "markdown"
        target, plan = _IDS["overnight_charge_target"], _IDS["charge_plan"]
        assert first["content"].startswith(f"{{% set plan = state_attr('{target}', 'plan') %}}### ")
        assert first["content"].endswith(f"\n<font color='#9e9e9e'>{{{{ states('{plan}') }}}}</font>")

    def test_the_other_figures_stay_after_it(self):
        cards = _battery_section("Tonight")[1:]
        assert _figure_names(cards) == ["Charge cost", "Sunrise if no charge"]
        assert [c["name"] for c in cards if c["type"] == "tile"] == [
            "Battery now",
            "At sunrise",
            "Fixed target",
            "Charge to",
            "Skip tonight",
            "Dry run",
            "Rate floor",
        ]

    @pytest.mark.parametrize(
        ("plan", "shown"),
        [("skip", "### No charge needed tonight"), ("charge", "### Charging to 80% tonight")],
    )
    def test_the_headline_says_no_charge_on_a_skipped_night_and_the_target_otherwise(
        self, plan, shown
    ):
        from tests.test_dashboard import _render

        first = _battery_section("Tonight")[0]
        target = _IDS["overnight_charge_target"]
        text = _render(first["content"], lambda e: "80", {(target, "plan"): plan})
        assert text.splitlines()[0] == shown

    def test_the_section_works_while_the_plan_sensor_is_off(self):
        cards = _battery_section("Tonight", registry=FakeRegistry(absent={"charge_plan"}))
        assert cards[0]["type"] == "markdown"
        assert "<font" not in cards[0]["content"]
        assert _IDS["charge_plan"] not in str(cards)


class TestTheTwoSunriseFigures:
    """The estimate at sunrise is shown without and with tonight's planned charge, by name."""

    _NO_CHARGE = "Sunrise if no charge"
    _WITH_CHARGE = "At sunrise"

    @classmethod
    def _figures(cls, *, registry=None) -> dict[str, dict]:
        cards = _battery_section("Tonight", registry=registry)
        rows = {r["name"]: r for c in cards if c["type"] == "glance" for r in c["entities"]}
        return rows | {c["name"]: c for c in cards if c["type"] == "tile"}

    def test_each_figure_has_a_name_that_says_which_it_is(self):
        figures = self._figures()
        assert figures[self._NO_CHARGE]["entity"] == _IDS["estimated_soc_at_sunrise"]
        assert figures[self._WITH_CHARGE]["entity"] == _IDS["estimated_soc_at_sunrise_with_charge"]

    def test_the_with_charge_bar_is_full_width_beside_the_battery_now(self):
        tile = self._figures()[self._WITH_CHARGE]
        assert tile["grid_options"]["columns"] == "full"
        assert tile["features"] == [{"type": "bar-gauge", "min": 0, "max": 100}]
        for name in (self._NO_CHARGE, self._WITH_CHARGE):
            assert len(name) <= 22

    def test_the_figures_sit_together_in_tonight(self):
        cards = _battery_section("Tonight")
        kinds = [(c["type"], c.get("name")) for c in cards]
        glance = next(i for i, c in enumerate(cards) if c["type"] == "glance")
        assert kinds[glance + 1 : glance + 3] == [("tile", "Battery now"), ("tile", self._WITH_CHARGE)]

    def test_the_tonight_view_shows_them_once(self):
        config = yaml.safe_load(dashboard_text())
        view = next(v for v in config["views"] if v["path"] == "plan")
        names = [c.get("name") for c in view_cards(view)] + _figure_names(view_cards(view))
        assert names.count(self._NO_CHARGE) == names.count(self._WITH_CHARGE) == 1

    def test_a_figure_is_left_out_while_its_sensor_is_not_there(self):
        absent = FakeRegistry(absent={"estimated_soc_at_sunrise_with_charge"})
        figures = self._figures(registry=absent)
        assert self._WITH_CHARGE not in figures
        assert self._NO_CHARGE in figures


class TestChargeSettingsInForce:
    def _names(self, switch_state: str) -> list[str]:
        return [c.get("name") for c in _battery_seen("Tonight", switch_state)]

    def test_the_override_value_shows_only_while_the_override_is_on(self):
        assert "Charge to" in self._names("on")
        assert "Charge to" not in self._names("off")

    def test_the_fixed_target_shows_only_while_it_is_on(self):
        """Tonight lists only what changes it tonight, so an unused switch is hidden."""
        assert "Fixed target" in self._names("on")
        assert "Fixed target" not in self._names("off")

    def test_the_value_is_hidden_by_a_condition_on_the_switch_state(self):
        card = next(c for c in _battery_section("Tonight") if c.get("name") == "Charge to")
        assert card["visibility"] == [
            {
                "condition": "state",
                "entity": _IDS["charge_target_override_enabled"],
                "state": "on",
            }
        ]

    def test_dry_run_reads_on_or_off_from_the_summary_attribute(self):
        card = next(c for c in _battery_section("Tonight") if c.get("name") == "Dry run")
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

    def test_no_word_on_the_dashboard_says_survival(self):
        text = re.sub(r"(sensor|switch|number)\.[a-z0-9_]+", "", dashboard_text())
        header_free = text[text.index("views:") :]
        assert "survival" not in header_free.lower()
