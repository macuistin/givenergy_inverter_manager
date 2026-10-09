"""
The Energy today tiles and the "Where today's energy came from" card of the dashboard.

The card is a markdown template, so these tests render it with Jinja and the template
functions Home Assistant provides (tests/test_dashboard.py holds the stand-ins). The figures
are a real day: 12.1 kWh imported, 7.5 of it into the battery, 11.3 kWh used by the house,
1.8 kWh discharged from the battery.
"""

from __future__ import annotations

import pytest
import yaml

from custom_components.givenergy_inverter_manager.dashboard.templates import (
    EnergySources,
    energy_devices_template,
    energy_sources_template,
)
from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    view_cards,
)
from tests.test_dashboard import _render

IDS = default_entity_ids()
CARD = IDS["self_sufficiency"]
HOUSE = IDS["house_kwh_today"]
IMPORTED = IDS["import_today"]
DISCHARGE = IDS["battery_discharge_kwh_today"]

HEADING = "Where today's energy came from"

# The attributes the self-sufficiency sensor carries when it knows where the grid energy went.
SPLIT_ATTRS = {
    "house_load_kwh": 11.3,
    "from_grid_kwh": 4.6,
    "grid_to_battery_kwh": 7.5,
    "from_solar_and_battery_kwh": 6.7,
    "basis": "ac_charge_counter",
}


def _text(
    *,
    attrs: dict | None = None,
    states: dict | None = None,
    sources: EnergySources | None = None,
) -> str:
    """The card rendered for a day, as the person reads it."""
    sources = sources or EnergySources(CARD, HOUSE, IMPORTED, DISCHARGE)
    values = {CARD: "59.3", HOUSE: "11.3", IMPORTED: "12.1", DISCHARGE: "1.8", **(states or {})}
    attributes = {(CARD, name): value for name, value in (attrs or {}).items()}
    template = energy_sources_template(sources)
    return _render(template, lambda e: values.get(e, "unknown"), attributes).strip()


class TestTheHouseLine:
    def test_the_live_day_adds_up_to_the_house_use(self):
        assert "House used **11.3 kWh**: solar 4.9 + battery 1.8 + grid 4.6." in _text(
            attrs=SPLIT_ATTRS
        )

    def test_solar_and_battery_are_one_figure_without_the_battery_sensor(self):
        text = _text(attrs=SPLIT_ATTRS, sources=EnergySources(CARD, HOUSE, IMPORTED))
        assert "House used **11.3 kWh**: solar and battery 6.7 + grid 4.6." in text

    def test_solar_and_battery_are_one_figure_while_the_battery_sensor_has_no_reading(self):
        text = _text(attrs=SPLIT_ATTRS, states={DISCHARGE: "unavailable"})
        assert "solar and battery 6.7 + grid 4.6." in text

    def test_the_battery_never_supplies_more_than_the_house_took_from_storage(self):
        text = _text(attrs=SPLIT_ATTRS, states={DISCHARGE: "9.0"})
        assert "solar 0.0 + battery 6.7 + grid 4.6." in text

    def test_without_the_attributes_the_house_and_import_totals_stand_in(self):
        """An older build sets no attributes: import counts as the house's, up to its use."""
        text = _text()
        assert "House used **11.3 kWh**: solar 0.0 + battery 0.0 + grid 11.3." in text

    def test_an_import_below_the_house_use_leaves_the_rest_to_solar_and_battery(self):
        text = _text(states={IMPORTED: "3.0", DISCHARGE: "1.0"})
        assert "solar 7.3 + battery 1.0 + grid 3.0." in text


class TestTheGridLine:
    def test_it_splits_the_import_between_the_house_and_the_battery(self):
        assert "Grid import **12.1 kWh**: 4.6 for the house + 7.5 into the battery." in _text(
            attrs=SPLIT_ATTRS
        )

    def test_a_day_with_no_grid_charging_says_so(self):
        attrs = {**SPLIT_ATTRS, "from_grid_kwh": 2.0, "grid_to_battery_kwh": 0.0}
        text = _text(attrs=attrs, states={IMPORTED: "2.0"})
        assert "Grid import **2.0 kWh**: 2.0 for the house + 0.0 into the battery." in text

    def test_it_does_not_split_an_import_it_cannot_split(self):
        attrs = {"house_load_kwh": 11.3, "from_grid_kwh": 11.3, "basis": "import_only"}
        text = _text(attrs=attrs)
        assert "into the battery." not in text
        assert "How much of it went into the battery is not known" in text

    def test_an_older_build_with_no_basis_is_not_split_either(self):
        assert "is not known" in _text()


class TestTheMeaning:
    def test_it_names_the_figure_and_says_what_it_is(self):
        text = _text(attrs=SPLIT_ATTRS)
        assert (
            "**Self-sufficiency 59%** is the share of what the house used that did not come "
            "from the grid." in text
        )

    def test_it_does_not_print_a_figure_the_sensor_does_not_have(self):
        text = _text(attrs=SPLIT_ATTRS, states={CARD: "unavailable"})
        assert "**Self-sufficiency** is the share" in text
        assert "0%" not in text


class TestWithoutTodaysTotals:
    @pytest.mark.parametrize("state", ["unavailable", "unknown"])
    def test_the_card_waits_when_the_house_use_is_not_known(self, state):
        text = _text(states={HOUSE: state})
        assert text == "Waiting for today's energy totals."

    def test_the_card_waits_when_the_import_is_not_known(self):
        assert _text(attrs=SPLIT_ATTRS, states={IMPORTED: "unavailable"}) == (
            "Waiting for today's energy totals."
        )

    def test_the_attribute_for_the_house_use_is_enough_without_the_house_sensor(self):
        text = _text(attrs=SPLIT_ATTRS, states={HOUSE: "unavailable"})
        assert "House used **11.3 kWh**" in text


class TestTheDeviceLine:
    def test_it_names_the_ev_and_the_immersion_with_their_energy(self):
        text = energy_devices_template("sensor.car", "sensor.heater")
        states = {"sensor.car": "2.46", "sensor.heater": "1.04"}
        rendered = _render(text, lambda e: states[e])
        assert rendered == "Of the house use, the EV took 2.5 kWh and the immersion took 1.0 kWh."

    def test_it_names_only_the_device_given(self):
        assert energy_devices_template("sensor.car", None) == (
            "Of the house use, the EV took {{ states('sensor.car') | float(0) | round(1) }} kWh."
        )
        assert "EV" not in energy_devices_template(None, "sensor.heater")

    def test_it_is_nothing_with_no_device(self):
        assert energy_devices_template(None, None) is None


# ── the dashboard ────────────────────────────────────────────────────────────


def _view(config: dict, path: str) -> dict:
    return next(v for v in config["views"] if v["path"] == path)


def _section(view: dict, heading: str) -> dict | None:
    for section in view["sections"]:
        if section["cards"][0].get("heading") == heading:
            return section
    return None


def _generated(**registry) -> dict:
    return dashboard_dict(FULL_CONFIG, FakeRegistry(enable_all=True, **registry))


class TestEnergyTodayTiles:
    def _tiles(self, config: dict) -> dict[str, dict]:
        section = _section(_view(config, "power-flow"), "Energy today")
        return {c["name"]: c for c in section["cards"] if c["type"] == "tile"}

    def test_self_sufficiency_joins_the_four_totals(self):
        tiles = self._tiles(_generated())
        totals = [n for n in tiles if n in {"Generated", "Used", "Imported", "Exported", "Self-sufficient"}]
        assert totals == ["Generated", "Used", "Imported", "Exported", "Self-sufficient"]
        assert tiles["Self-sufficient"]["entity"] == IDS["self_sufficiency"]

    def test_a_tile_is_left_out_when_its_sensor_is_missing(self):
        tiles = self._tiles(_generated(absent={"self_sufficiency"}))
        assert "Self-sufficient" not in tiles
        assert "Used" in tiles


class TestTheSourcesGroup:
    def _group(self, config: dict) -> dict | None:
        return _section(_view(config, "today"), HEADING)

    def test_it_sits_under_energy_on_the_today_tab(self):
        headings = [s["cards"][0].get("heading") for s in _view(_generated(), "today")["sections"]]
        assert headings[:2] == ["Energy", HEADING]

    def test_it_reads_the_self_sufficiency_house_and_import_sensors(self):
        group = self._group(_generated())
        card = next(c for c in group["cards"] if c["type"] == "markdown")
        assert card["grid_options"] == {"columns": "full"}
        for entity in (CARD, HOUSE, IMPORTED):
            assert f"'{entity}'" in card["content"]

    def test_it_names_the_battery_sensor_when_that_sensor_is_enabled(self):
        group = self._group(_generated())
        assert f"'{DISCHARGE}'" in group["cards"][1]["content"]

    def test_it_names_the_battery_sensor_on_a_fresh_install(self):
        config = dashboard_dict(FULL_CONFIG, FakeRegistry())
        group = self._group(config)
        assert group is not None
        assert f"'{DISCHARGE}'" in group["cards"][1]["content"]

    def test_it_leaves_the_battery_out_when_the_user_has_disabled_that_sensor(self):
        registry = FakeRegistry(enable_all=True)
        registry.async_get(DISCHARGE).disabled_by = "user"
        group = self._group(dashboard_dict(FULL_CONFIG, registry))
        assert group is not None
        assert "set battery_entity = ''" in group["cards"][1]["content"]

    @pytest.mark.parametrize("missing", ["self_sufficiency", "house_kwh_today", "import_today"])
    def test_it_is_left_out_with_no_heading_when_a_sensor_it_reads_is_missing(self, missing):
        config = _generated(absent={missing})
        assert self._group(config) is None
        assert HEADING not in yaml.safe_dump(config)

    def test_it_is_valid_in_the_markdown_card_of_the_frontend(self):
        group = self._group(_generated())
        for card in group["cards"]:
            if card["type"] == "markdown":
                assert _render(card["content"], lambda entity: "1.0")


class TestSelfSufficiencyIsShownOnce:
    """Self-sufficiency is stated, with its meaning, by the sources card of the Today tab.

    The Power Flow tab keeps a tile for a glance. The Today tab does not repeat it as a bar
    unless the sources card is missing, so the figure is never lost.
    """

    def _bars(self, config: dict) -> list[str]:
        section = _section(_view(config, "today"), "Solar")
        return [c["name"] for c in section["cards"] if c["type"] == "tile"]

    def _says_it_in_words(self, config: dict) -> bool:
        group = _section(_view(config, "today"), HEADING)
        return bool(group) and any(CARD in c.get("content", "") for c in group["cards"])

    def test_the_today_bars_leave_it_out_while_the_card_states_it(self):
        config = _generated()
        assert self._says_it_in_words(config)
        assert self._bars(config) == ["Home use from solar", "Solar kept at home"]

    def test_no_tile_of_the_today_tab_repeats_the_figure(self):
        cards = view_cards(_view(_generated(), "today"))
        assert [c for c in cards if c["type"] == "tile" and c["entity"] == CARD] == []

    def test_the_power_flow_tile_stays(self):
        tiles = TestEnergyTodayTiles()._tiles(_generated())
        assert tiles["Self-sufficient"]["entity"] == CARD

    @pytest.mark.parametrize("missing", ["house_kwh_today", "import_today"])
    def test_the_bar_returns_when_the_card_cannot_be_built(self, missing):
        """Losing the card must not lose the figure."""
        config = _generated(absent={missing})
        assert not self._says_it_in_words(config)
        assert self._bars(config) == ["Self-sufficiency", "Home use from solar", "Solar kept at home"]

    def test_the_figure_is_gone_from_the_today_tab_when_its_sensor_is_missing(self):
        config = _generated(absent={"self_sufficiency"})
        assert self._bars(config) == ["Home use from solar", "Solar kept at home"]
        assert CARD not in yaml.safe_dump(_view(config, "today"))
