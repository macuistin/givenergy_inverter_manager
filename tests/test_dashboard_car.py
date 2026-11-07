"""The car's plug state, battery level, location and power show beside the charger."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.const import CONF_CARS
from tests.dashboard_support import dashboard_dict, default_entity_ids, devices_of, view_cards
from tests.dashboard_visibility import install, seen, states_with

IDS = default_entity_ids()
CAR = {
    "car_name": "Family car",
    "car_battery_level_entity": "sensor.car_battery",
    "car_plug_entity": "binary_sensor.car_plug",
    "car_tracker_entity": "device_tracker.car",
}
CAR_KEYS = ("car_plug_status", "car_battery_level", "car_at_home", "car_charging_power")


def _page(path: str, *, with_car: bool) -> dict:
    config, brand = install(ev=True)
    if with_car:
        config = {**config, CONF_CARS: [CAR]}
    generated = dashboard_dict(config, ev_brand=brand)
    shown = seen(generated, states_with(devices_of(config, brand)))
    return next(v for v in shown["views"] if v["path"] == path)


def _tile_entities(view: dict) -> set[str]:
    return {c["entity"] for c in view_cards(view) if c["type"] == "tile"}


def _glance_entities(view: dict) -> set[str]:
    return {r["entity"] for c in view_cards(view) if c["type"] == "glance" for r in c["entities"]}


def test_home_energy_shows_the_car_tiles_when_a_car_is_set_up():
    tiles = _tile_entities(_page("power-flow", with_car=True))
    assert {IDS[key] for key in CAR_KEYS} <= tiles


def test_home_energy_leaves_the_car_out_when_none_is_set_up():
    tiles = _tile_entities(_page("power-flow", with_car=False))
    assert not {IDS[key] for key in CAR_KEYS} & tiles


def test_the_ev_view_shows_the_car_figures_when_a_car_is_set_up():
    glance = _glance_entities(_page("ev-charger", with_car=True))
    assert {IDS[key] for key in CAR_KEYS} <= glance


def test_the_ev_view_leaves_the_car_out_when_none_is_set_up():
    glance = _glance_entities(_page("ev-charger", with_car=False))
    assert not {IDS[key] for key in CAR_KEYS} & glance
