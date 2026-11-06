"""The coordinator reads the car set up in the options and decides if it is plugged in at home."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.discovery import EVCharger, EVChargerBrand
from custom_components.givenergy_inverter_manager.lib.ev import PlugSource, PlugState
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

CAR = {
    "car_name": "Family car",
    "car_battery_level_entity": "sensor.car_battery",
    "car_plug_entity": "binary_sensor.car_plug",
    "car_tracker_entity": "device_tracker.car",
}
PLUG = "sensor.myenergi_zappi_plug_status"


def _coordinator(with_car: bool = True, with_charger: bool = False) -> FakeCoordinator:
    cfg = _cfg()
    if with_car:
        cfg["cars"] = [CAR]
    coord = FakeCoordinator(cfg=cfg)
    coord.set_states(_default_states())
    if with_charger:
        coord._ev_charger = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="1",
            display_name="Zappi",
            status_entity=PLUG,
        )
    return coord


@pytest.mark.asyncio
async def test_no_car_set_up_leaves_the_car_fields_empty():
    coord = _coordinator(with_car=False)

    data = await coord.run_cycle()

    assert data.car_reading is None
    assert data.car_plug is None


@pytest.mark.asyncio
async def test_a_plugged_in_car_at_home_with_no_charger_is_plugged_in():
    coord = _coordinator()
    coord.set_states(
        {
            "sensor.car_battery": "55",
            "binary_sensor.car_plug": "on",
            "device_tracker.car": "home",
        }
    )

    data = await coord.run_cycle()

    assert data.car_reading.battery_pct == 55.0
    assert data.car_plug.state is PlugState.PLUGGED_IN
    assert data.car_plug.source is PlugSource.CAR


@pytest.mark.asyncio
async def test_a_connected_charger_with_the_car_away_is_a_visitor():
    coord = _coordinator(with_charger=True)
    coord.set_states(
        {
            PLUG: "EV Connected",
            "binary_sensor.car_plug": "off",
            "device_tracker.car": "not_home",
        }
    )

    data = await coord.run_cycle()

    assert data.car_plug.state is PlugState.PLUGGED_IN
    assert data.car_plug.car_matches is False
    assert data.car_plug.conflict is True


@pytest.mark.asyncio
async def test_the_charge_plan_still_follows_the_charger_alone():
    coord = _coordinator(with_charger=True)
    coord.set_states(
        {
            PLUG: "EV Disconnected",
            "binary_sensor.car_plug": "on",
            "device_tracker.car": "home",
        }
    )

    data = await coord.run_cycle()

    assert data.car_plug.state is PlugState.PLUGGED_IN
    assert coord._ev_charger.is_plugged_in is False
