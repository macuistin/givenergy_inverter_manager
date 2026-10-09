"""Which sensors setup enables once they are on by default, chosen without Home Assistant."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.default_enabled import (
    NEWLY_ENABLED_SENSOR_KEYS,
    keys_to_enable,
)


def test_the_five_sensors_are_listed():
    assert set(NEWLY_ENABLED_SENSOR_KEYS) == {
        "saving_vs_grid_today",
        "net_saving_today",
        "battery_discharge_kwh_today",
        "next_cheap_rate_start",
        "charge_plan",
    }


def test_each_one_the_integration_disabled_is_selected():
    held = ["charge_plan", "net_saving_today", "next_cheap_rate_start", "saving_vs_grid_today"]
    assert keys_to_enable(held) == [
        "saving_vs_grid_today",
        "net_saving_today",
        "next_cheap_rate_start",
        "charge_plan",
    ]


def test_other_sensors_are_never_selected():
    assert keys_to_enable(["hours_to_cheap_rate", "battery_charge_kwh_today"]) == []


def test_nothing_is_selected_when_the_integration_disabled_none():
    assert keys_to_enable([]) == []
