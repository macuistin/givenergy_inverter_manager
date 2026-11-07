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


def _plan_coordinator(capacity: float | None, battery: str = "40") -> FakeCoordinator:
    car = {**CAR, "car_battery_capacity_kwh": capacity} if capacity else CAR
    cfg = _cfg()
    cfg["cars"] = [car]
    coord = FakeCoordinator(cfg=cfg)
    coord.set_states(_default_states())
    coord._ev_charger = EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="1",
        display_name="Zappi",
        status_entity=PLUG,
    )
    coord.set_states(
        {
            PLUG: "EV Connected",
            "sensor.car_battery": battery,
            "binary_sensor.car_plug": "on",
            "device_tracker.car": "home",
        }
    )
    return coord


@pytest.mark.asyncio
async def test_the_plan_names_the_car_level_and_what_it_needs():
    data = await _plan_coordinator(capacity=60.0).run_cycle()

    assert "The car is at 40%, about 36 kWh to reach 100%." in data.ev_charging_plan


@pytest.mark.asyncio
async def test_the_plan_gives_only_the_level_without_a_battery_size():
    data = await _plan_coordinator(capacity=None).run_cycle()

    assert data.ev_charging_plan.endswith("The car is at 40%.")


@pytest.mark.asyncio
async def test_the_plan_says_nothing_about_a_visitors_car():
    coord = _plan_coordinator(capacity=60.0)
    coord.set_states({"binary_sensor.car_plug": "off", "device_tracker.car": "not_home"})

    data = await coord.run_cycle()

    assert "The car is" not in data.ev_charging_plan


@pytest.mark.asyncio
async def test_no_car_leaves_the_plan_as_it_was():
    coord = _coordinator(with_car=False, with_charger=True)
    coord.set_states({PLUG: "EV Connected"})

    data = await coord.run_cycle()

    assert "The car is" not in data.ev_charging_plan
