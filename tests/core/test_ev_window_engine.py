"""The engine asks for Fast inside the owner's charge window and reads the window from the options."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from tests.conftest import _nightboost_cfg, _raw, _run


def _zappi(mode: str = "Eco+") -> EVCharger:
    return EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="123",
        display_name="Zappi (123)",
        state=EVChargerState.CONNECTED,
        charge_mode=mode,
        charge_mode_entity="select.zappi_123_charge_mode",
    )


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 19, hour, minute)


def _cycle(now: datetime, mode: str = "Eco+", **cfg):
    raw = _raw(ev_plugged_in=True)
    return _run(raw=raw, cfg={**_nightboost_cfg(), **cfg}, now=now, ev_charger=_zappi(mode))


@pytest.mark.parametrize("hour", [23, 0, 3, 8])
def test_by_default_the_car_gets_fast_from_23_00_to_09_00(hour):
    data, target = _cycle(_at(hour))
    assert target == "Fast"
    assert data.ev_charging_window == "23:00 to 09:00"


@pytest.mark.parametrize("hour", [9, 12, 22])
def test_outside_the_default_window_nothing_asks_for_fast(hour):
    _, target = _cycle(_at(hour))
    assert target is None


def test_the_window_is_not_tied_to_the_tariff():
    """08:30 is the Day rate on the Nightboost tariff, and the window still holds."""
    _, target = _cycle(_at(8, 30))
    assert target == "Fast"


def test_the_start_and_end_times_come_from_the_options():
    cfg = {"ev_start_time": "22:00", "ev_end_time": "07:00"}
    assert _cycle(_at(22, 30), **cfg)[1] == "Fast"
    assert _cycle(_at(8), **cfg)[1] is None
    assert _cycle(_at(8), **cfg)[0].ev_charging_window == "22:00 to 07:00"


def test_a_value_that_is_not_a_time_falls_back_to_the_default():
    assert _cycle(_at(2), ev_start_time="late")[1] == "Fast"


def test_a_charger_already_in_fast_is_not_asked_again():
    assert _cycle(_at(2), mode="Fast")[1] is None
