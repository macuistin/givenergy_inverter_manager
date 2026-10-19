"""Finding a forecast sensor and immersion switch candidates for the setup wizard."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.givenergy_inverter_manager.discovery import (
    ForecastSensors,
    discover_forecast_sensors,
    discover_immersion_switch_candidates,
    todays_forecast_sensor,
)

SOLCAST_TOMORROW = "sensor.solcast_pv_forecast_forecast_tomorrow"
SOLCAST_DAY_3 = "sensor.solcast_pv_forecast_forecast_day_3"
FORECAST_SOLAR = "sensor.energy_production_tomorrow"


def _states(*entity_ids: str, **names: str) -> dict:
    return {
        entity_id: SimpleNamespace(state="on", attributes={"friendly_name": names.get(entity_id)})
        for entity_id in entity_ids
    }


def test_nothing_is_found_when_no_forecast_integration_is_installed():
    assert discover_forecast_sensors(_states("sensor.something_else")) is None


def test_solcast_is_found_with_its_day_after_tomorrow_sensor():
    found = discover_forecast_sensors(_states(SOLCAST_TOMORROW, SOLCAST_DAY_3))

    assert found == ForecastSensors("Solcast", SOLCAST_TOMORROW, SOLCAST_DAY_3)


def test_solcast_without_a_day_3_sensor_has_no_day_after_tomorrow():
    found = discover_forecast_sensors(_states(SOLCAST_TOMORROW))

    assert found == ForecastSensors("Solcast", SOLCAST_TOMORROW, None)


def test_forecast_solar_is_found():
    found = discover_forecast_sensors(_states(FORECAST_SOLAR))

    assert found == ForecastSensors("Forecast.Solar", FORECAST_SOLAR, None)


def test_the_first_provider_in_the_list_wins_when_both_exist():
    found = discover_forecast_sensors(_states(FORECAST_SOLAR, SOLCAST_TOMORROW))

    assert found.provider == "Solcast"


def test_a_day_3_sensor_alone_is_not_a_forecast():
    assert discover_forecast_sensors(_states(SOLCAST_DAY_3)) is None


def test_immersion_candidates_match_the_entity_id_or_the_friendly_name():
    states = _states(
        "switch.immersion_heater",
        "switch.cylinder_relay",
        "switch.lamp",
        "light.immersion_lamp",
        **{"switch.cylinder_relay": "Hot water Immersion"},
    )

    assert discover_immersion_switch_candidates(states) == (
        "switch.cylinder_relay",
        "switch.immersion_heater",
    )


def test_immersion_candidates_are_limited_to_five_and_sorted():
    states = _states(*(f"switch.immersion_{n}" for n in range(9, 0, -1)))

    found = discover_immersion_switch_candidates(states)

    assert found == tuple(f"switch.immersion_{n}" for n in range(1, 6))


def test_no_candidates_when_no_switch_looks_like_an_immersion():
    assert discover_immersion_switch_candidates(_states("switch.lamp")) == ()


def test_the_today_sensor_of_solcast_is_found_from_the_tomorrow_one():
    assert todays_forecast_sensor(SOLCAST_TOMORROW) == "sensor.solcast_pv_forecast_forecast_today"


def test_a_renamed_pair_keeps_its_prefix():
    assert todays_forecast_sensor("sensor.roof_tomorrow") == "sensor.roof_today"


def test_a_sensor_that_is_not_for_tomorrow_has_no_today_sensor():
    assert todays_forecast_sensor(SOLCAST_DAY_3) is None
    assert todays_forecast_sensor(None) is None
