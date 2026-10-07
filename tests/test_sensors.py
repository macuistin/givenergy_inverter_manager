"""
Tests for the sensor description table and the sensor entity.

sensor.py imports under the conftest Home Assistant stubs, so the tests read the
real SENSOR_DESCRIPTIONS and call each description's value_fn directly. The
decision logic behind the extracted value functions is tested in
test_sensor_values.py.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower

from custom_components.givenergy_inverter_manager.const import DEFAULT_CURRENCY_SYMBOL
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.sensor import (
    SENSOR_DESCRIPTIONS,
    GivEnergyManagerSensor,
)

_BY_KEY = {d.key: d for d in SENSOR_DESCRIPTIONS}


def _sensor_keys() -> set[str]:
    """All keys in SENSOR_DESCRIPTIONS."""
    return set(_BY_KEY)


def _lambda_for(key: str):
    """Return the value_fn of the description with the given key."""
    return _BY_KEY[key].value_fn


class TestSensorKeysExist:
    """Every expected sensor key must be declared."""

    @pytest.mark.parametrize(
        "key",
        [
            "solar_power",
            "battery_soc",
            "battery_power",
            "grid_power",
            "house_load",
        ],
    )
    def test_sensor_declared(self, key):
        assert key in _sensor_keys(), (
            f"Sensor {key!r} not found in SENSOR_DESCRIPTIONS. Known keys: {sorted(_sensor_keys())}"
        )


class TestBatteryPowerMetadata:
    """battery_power must be a watts power sensor, the power-flow-card depends on it."""

    def test_unit_is_watt(self):
        assert _BY_KEY["battery_power"].native_unit_of_measurement is UnitOfPower.WATT

    def test_device_class_is_power(self):
        assert _BY_KEY["battery_power"].device_class is SensorDeviceClass.POWER

    def test_state_class_is_measurement(self):
        assert _BY_KEY["battery_power"].state_class is SensorStateClass.MEASUREMENT


class TestBatteryPowerValueFn:
    """value_fn must read battery_power_w, not some other attribute."""

    @staticmethod
    def _data(power_w):
        d = MagicMock()
        d.battery_power_w = power_w
        d.battery_soc = 77.0
        return d

    def test_reads_battery_power_w_not_battery_soc(self):
        assert _lambda_for("battery_power")(self._data(2500.0)) == pytest.approx(2500.0)

    def test_charging(self):
        assert _lambda_for("battery_power")(self._data(2500.0)) == pytest.approx(2500.0)

    def test_discharging(self):
        assert _lambda_for("battery_power")(self._data(-1800.0)) == pytest.approx(-1800.0)

    def test_rounds_to_one_decimal(self):
        assert _lambda_for("battery_power")(self._data(2500.456)) == pytest.approx(2500.5)


class TestGridPowerMetadata:
    def test_device_class_is_power(self):
        assert _BY_KEY["grid_power"].device_class is SensorDeviceClass.POWER

    def test_unit_is_watt(self):
        assert _BY_KEY["grid_power"].native_unit_of_measurement is UnitOfPower.WATT

    def test_state_class_is_measurement(self):
        assert _BY_KEY["grid_power"].state_class is SensorStateClass.MEASUREMENT


class TestImmersionPowerMetadata:
    """immersion_power must be a watts sensor reading data.immersion_load_w."""

    def test_sensor_declared(self):
        assert "immersion_power" in _sensor_keys()

    def test_unit_is_watt(self):
        assert _BY_KEY["immersion_power"].native_unit_of_measurement is UnitOfPower.WATT

    def test_device_class_is_power(self):
        assert _BY_KEY["immersion_power"].device_class is SensorDeviceClass.POWER

    def test_state_class_is_measurement(self):
        assert _BY_KEY["immersion_power"].state_class is SensorStateClass.MEASUREMENT

    def test_value_fn_uses_immersion_load_w(self):
        d = MagicMock()
        d.immersion_load_w = 1234.0
        d.battery_power_w = 1.0
        assert _lambda_for("immersion_power")(d) == pytest.approx(1234.0)

    def test_on_when_running(self):
        d = MagicMock()
        d.immersion_load_w = 3000.0
        assert _lambda_for("immersion_power")(d) == pytest.approx(3000.0)

    def test_off_is_zero(self):
        d = MagicMock()
        d.immersion_load_w = 0.0
        assert _lambda_for("immersion_power")(d) == pytest.approx(0.0)


class TestSolarForecastSensors:
    """The charge plan and the provider forecasts are separate sensors with different sources."""

    def test_provider_forecast_is_an_energy_sensor_without_a_state_class(self):
        description = _BY_KEY["solar_forecast_raw_today"]
        assert description.device_class is SensorDeviceClass.ENERGY
        assert description.native_unit_of_measurement is UnitOfEnergy.KILO_WATT_HOUR
        assert description.state_class is None
        assert description.entity_registry_enabled_default is True

    def test_the_two_forecast_sensors_read_different_fields(self):
        data = CoordinatorData()
        data.solar_forecast_kwh_today = 31.5
        data.solar_forecast_raw_kwh_today = 38.96
        assert _lambda_for("solar_forecast_kwh_today")(data) == pytest.approx(31.5)
        assert _lambda_for("solar_forecast_raw_today")(data) == pytest.approx(38.96)

    def test_the_percentage_follows_the_provider_forecast(self):
        data = CoordinatorData()
        data.solar_forecast_kwh_today = 31.5
        data.solar_forecast_raw_kwh_today = 40.0
        data.today.solar_kwh = 30.0
        assert _lambda_for("solar_actual_vs_forecast_pct")(data) == pytest.approx(75.0)


class TestWeeklyMonthlySensorStateClass:
    """Weekly and monthly sensors must use TOTAL not TOTAL_INCREASING.
    They can decrease from floating-point rounding, causing recorder warnings."""

    def test_period_sensors_use_total_not_total_increasing(self):
        period_sensors = [
            d
            for d in SENSOR_DESCRIPTIONS
            if d.reset_period is not None or d.key.endswith(("_this_week", "_this_month"))
        ]
        assert period_sensors
        assert [
            d.key for d in period_sensors if d.state_class is SensorStateClass.TOTAL_INCREASING
        ] == [], (
            "Weekly/monthly sensors must use SensorStateClass.TOTAL not TOTAL_INCREASING, "
            "float rounding can cause micro-decreases that trigger HA recorder warnings."
        )

    def test_only_the_ev_session_counter_is_total_increasing(self):
        increasing = {
            d.key for d in SENSOR_DESCRIPTIONS if d.state_class is SensorStateClass.TOTAL_INCREASING
        }
        assert increasing == {"ev_session_energy"}


class TestThroughputBudgetSensors:
    """Budget sensors are disabled diagnostics that read the engine fields."""

    def test_pct_sensor_state_class_is_measurement(self):
        assert _BY_KEY["battery_throughput_budget_pct"].state_class is SensorStateClass.MEASUREMENT

    def test_pct_value_fn_rounds_and_handles_none(self):
        fn = _lambda_for("battery_throughput_budget_pct")
        d = MagicMock()
        d.battery_throughput_budget_pct = 83.456
        assert fn(d) == pytest.approx(83.5)
        d.battery_throughput_budget_pct = None
        assert fn(d) is None

    def test_status_value_fn_returns_none_when_unset(self):
        fn = _lambda_for("battery_throughput_budget_status")
        d = MagicMock()
        d.battery_throughput_budget_status = ""
        assert fn(d) is None
        d.battery_throughput_budget_status = "High"
        assert fn(d) == "High"


class TestBatteryYearsRemainingSensor:
    def test_value_fn_rounds_and_handles_none(self):
        fn = _lambda_for("battery_years_remaining")
        d = MagicMock()
        d.battery_years_remaining = 12.345
        assert fn(d) == pytest.approx(12.3)
        d.battery_years_remaining = None
        assert fn(d) is None


class TestAvgImportRateSensors:
    """Average import rate = import cost / import kWh, None when nothing was imported."""

    @pytest.mark.parametrize(
        ("key", "period"),
        [
            ("avg_import_rate_today", "today"),
            ("avg_import_rate_this_week", "week"),
            ("avg_import_rate_this_month", "month"),
        ],
    )
    def test_value_fn(self, key, period):
        fn = _lambda_for(key)
        d = MagicMock()
        acc = getattr(d, period)
        acc.total_import_cost = 3.0
        acc.import_kwh = 10.0
        assert fn(d) == pytest.approx(0.3)
        acc.import_kwh = 0.0
        assert fn(d) is None

    @pytest.mark.parametrize(
        "key",
        ["avg_import_rate_today", "avg_import_rate_this_week", "avg_import_rate_this_month"],
    )
    def test_state_class_is_measurement(self, key):
        assert _BY_KEY[key].state_class is SensorStateClass.MEASUREMENT


class TestSolarShareSensors:
    """Solar share reads solar_share_pct of the matching period, to one decimal place."""

    _PERIODS = (
        ("solar_share", "today"),
        ("solar_share_yesterday", "yesterday"),
        ("solar_share_this_week", "week"),
        ("solar_share_this_month", "month"),
    )

    @pytest.mark.parametrize(("key", "period"), _PERIODS)
    def test_value_fn_reads_the_period_and_rounds(self, key, period):
        data = CoordinatorData()
        acc = getattr(data, period)
        acc.house_kwh = 30.0
        acc.solar_kwh = 12.0
        acc.export_kwh = 1.0
        assert _lambda_for(key)(data) == pytest.approx(36.7)

    @pytest.mark.parametrize(("key", "period"), _PERIODS)
    def test_value_fn_is_zero_with_no_consumption(self, key, period):
        assert _lambda_for(key)(CoordinatorData()) == 0.0

    @pytest.mark.parametrize(("key", "period"), _PERIODS)
    def test_percentage_measurement_enabled_by_default(self, key, period):
        description = _BY_KEY[key]
        assert description.native_unit_of_measurement == "%"
        assert description.state_class is SensorStateClass.MEASUREMENT
        assert description.entity_registry_enabled_default is True

    @pytest.mark.parametrize(("key", "period"), _PERIODS)
    def test_matches_the_self_sufficiency_sibling_declaration(self, key, period):
        sibling = _BY_KEY[key.replace("solar_share", "self_sufficiency")]
        description = _BY_KEY[key]
        assert description.entity_registry_enabled_default == (
            sibling.entity_registry_enabled_default
        )
        assert description.state_class is sibling.state_class
        assert description.native_unit_of_measurement == sibling.native_unit_of_measurement


class TestEfficiencySensors:
    @pytest.mark.parametrize(
        ("key", "period"),
        [
            ("cheap_import_fraction_this_week", "week"),
            ("cheap_import_fraction_this_month", "month"),
        ],
    )
    def test_cheap_import_fraction(self, key, period):
        fn = _lambda_for(key)
        d = MagicMock()
        acc = getattr(d, period)
        acc.cheap_import_fraction = 0.625
        acc.import_kwh = 8.0
        assert fn(d) == pytest.approx(62.5)
        acc.import_kwh = 0.0
        assert fn(d) is None

    def test_roundtrip_efficiency_value(self):
        fn = _lambda_for("battery_roundtrip_efficiency_today")
        d = MagicMock()
        d.today.battery_charge_kwh = 10.0
        d.today.battery_discharge_kwh = 9.2
        assert fn(d) == pytest.approx(92.0)
        d.today.battery_charge_kwh = 0.0
        assert fn(d) is None

    def test_roundtrip_efficiency_is_not_a_daily_total(self):
        assert not _BY_KEY["battery_roundtrip_efficiency_today"].is_daily_total, "MEASUREMENT sensors must not set last_reset"


class TestNextCheapRateSensors:
    def test_start_shows_time_when_known(self):
        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = "23:00"
        d.hours_to_cheap_rate = 9.0
        assert fn(d) == "23:00"

    def test_start_shows_now_when_active(self):
        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = None
        d.hours_to_cheap_rate = 0.0
        assert fn(d) == "Now"

    def test_start_is_none_on_flat_tariff(self):
        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = None
        d.hours_to_cheap_rate = None
        assert fn(d) is None

    def test_start_exposes_the_summary_attribute(self):
        attrs_fn = _BY_KEY["next_cheap_rate_start"].attrs_fn
        d = MagicMock()
        d.next_cheap_rate_start = "23:00"
        d.hours_to_cheap_rate = 8.93
        assert attrs_fn(d) == {"summary": "23:00 (in 8 h 56 min)"}

    def test_hours_sensor_has_no_attributes(self):
        assert _BY_KEY["hours_to_cheap_rate"].attrs_fn is None

    def test_hours_value_fn(self):
        fn = _lambda_for("hours_to_cheap_rate")
        d = MagicMock()
        d.hours_to_cheap_rate = 9.0
        assert fn(d) == 9.0


class TestBatteryEnergySensors:
    @pytest.mark.parametrize(
        ("key", "attr", "section"),
        [
            ("battery_charge_kwh_today", "battery_charge_kwh", "today"),
            ("battery_discharge_kwh_today", "battery_discharge_kwh", "today"),
            ("house_kwh_today", "house_kwh", "today"),
        ],
    )
    def test_value_fn_rounds_to_three_places(self, key, attr, section):
        fn = _lambda_for(key)
        d = MagicMock()
        setattr(getattr(d, section), attr, 4.56789)
        assert fn(d) == pytest.approx(4.568)

    @pytest.mark.parametrize(
        "key", ["battery_charge_kwh_today", "battery_discharge_kwh_today", "house_kwh_today"]
    )
    def test_daily_energy_sensors_are_total(self, key):
        assert _BY_KEY[key].state_class is SensorStateClass.TOTAL


class TestMiscellaneousSensors:
    @pytest.mark.parametrize(
        ("power_w", "expected"),
        [
            (2500.0, "Charging"),
            (51.0, "Charging"),
            (50.0, "Idle"),
            (0.0, "Idle"),
            (-50.0, "Idle"),
            (-51.0, "Discharging"),
            (-1800.0, "Discharging"),
        ],
    )
    def test_battery_power_direction(self, power_w, expected):
        fn = _lambda_for("battery_power_direction")
        d = MagicMock()
        d.battery_power_w = power_w
        assert fn(d) == expected

    def test_days_in_period_value_fn(self):
        fn = _lambda_for("days_in_period")
        d = MagicMock()
        d.days_in_period = 12
        assert fn(d) == 12


class TestEvKmSensors:
    def test_km_value_fn(self):
        d = MagicMock()
        d.ev_km_charged_today = 42.5
        assert _lambda_for("ev_km_charged_today")(d) == 42.5

    def test_cost_per_km_value_fn(self):
        d = MagicMock()
        d.ev_cost_per_km_today = None
        assert _lambda_for("ev_cost_per_km_today")(d) is None

    def test_cost_per_km_is_not_a_daily_total(self):
        assert not _BY_KEY["ev_cost_per_km_today"].is_daily_total, "MEASUREMENT sensors must not set last_reset"


class TestDerivedSensors:
    def test_solar_capture_excludes_missed_solar_once(self):
        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 20.0
        d.today.missed_solar_kwh = 5.0
        assert fn(d) == pytest.approx(75.0)

    def test_solar_capture_full_when_nothing_missed(self):
        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 12.0
        d.today.missed_solar_kwh = 0.0
        assert fn(d) == pytest.approx(100.0)

    def test_solar_capture_never_negative(self):
        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 4.0
        d.today.missed_solar_kwh = 6.0
        assert fn(d) == pytest.approx(0.0)

    def test_solar_capture_none_without_solar(self):
        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 0.0
        d.today.missed_solar_kwh = 0.0
        assert fn(d) is None

    def test_solar_capture_is_not_a_daily_total(self):
        assert not _BY_KEY["solar_capture_efficiency_today"].is_daily_total, "MEASUREMENT sensors must not set last_reset"

    def test_usable_capacity_scales_with_remaining_life(self):
        fn = _lambda_for("battery_usable_capacity_kwh")
        d = MagicMock()
        d.battery_capacity_kwh = 10.0
        d.battery_stats.estimated_remaining_life_pct = 90.0
        assert fn(d) == pytest.approx(9.0)
        d.battery_capacity_kwh = 0.0
        assert fn(d) is None

    def test_net_position_this_month_rounds(self):
        fn = _lambda_for("net_position_this_month")
        d = MagicMock()
        d.month.net_position = 3.141592
        assert fn(d) == pytest.approx(3.1416)


class TestCheapestRateSensors:
    def test_zero_rate_is_reported(self):
        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.0
        d.cheapest_rate_name = "Free hour"
        assert fn(d) == 0.0

    def test_none_before_first_cycle(self):
        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.0
        d.cheapest_rate_name = ""
        assert fn(d) is None

    def test_rate_rounds_to_four_places(self):
        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.096512
        d.cheapest_rate_name = "Nightboost"
        assert fn(d) == pytest.approx(0.0965)

    def test_period_name(self):
        fn = _lambda_for("cheapest_rate_period")
        d = MagicMock()
        d.cheapest_rate_name = "Nightboost"
        assert fn(d) == "Nightboost"
        d.cheapest_rate_name = ""
        assert fn(d) is None


class TestRateStatusSensors:
    @pytest.mark.parametrize(
        ("key", "attr"),
        [("is_on_cheapest_rate", "is_on_cheapest_rate"), ("is_on_base_rate", "is_on_base_rate")],
    )
    def test_yes_no(self, key, attr):
        fn = _lambda_for(key)
        d = MagicMock()
        setattr(d, attr, True)
        assert fn(d) == "yes"
        setattr(d, attr, False)
        assert fn(d) == "no"


class TestPeriodTimeSensors:
    def test_minutes_remaining_passthrough(self):
        fn = _lambda_for("minutes_remaining_in_period")
        d = MagicMock()
        d.minutes_remaining_in_period = 60.0
        assert fn(d) == 60.0
        d.minutes_remaining_in_period = None
        assert fn(d) is None

    def test_rate_saving_reports_zero_at_base_rate(self):
        fn = _lambda_for("rate_savings_vs_daytime")
        d = MagicMock()
        d.rate_savings_vs_daytime = 0.0
        assert fn(d) == 0.0
        d.rate_savings_vs_daytime = 0.23694
        assert fn(d) == pytest.approx(0.2369)


class TestGridSolarStatusSensors:
    @pytest.mark.parametrize(
        ("grid_w", "expected"),
        [
            (1200.0, "Importing"),
            (51.0, "Importing"),
            (50.0, "Balanced"),
            (0.0, "Balanced"),
            (-50.0, "Balanced"),
            (-51.0, "Exporting"),
            (-3000.0, "Exporting"),
        ],
    )
    def test_grid_power_direction(self, grid_w, expected):
        fn = _lambda_for("grid_power_direction")
        d = MagicMock()
        d.grid_power_w = grid_w
        assert fn(d) == expected

    def test_solar_pct_of_max(self):
        fn = _lambda_for("solar_power_pct_of_max")
        d = MagicMock()
        d.solar_power_w = 2500.0
        d.inverter_max_w = 5000.0
        assert fn(d) == pytest.approx(50.0)

    def test_solar_pct_of_max_none_without_inverter_limit(self):
        fn = _lambda_for("solar_power_pct_of_max")
        d = MagicMock()
        d.solar_power_w = 2500.0
        d.inverter_max_w = 0.0
        assert fn(d) is None


class TestStatusSensors:
    @staticmethod
    def _battery(soc, power):
        d = MagicMock()
        d.battery_soc = soc
        d.battery_power_w = power
        return d

    @pytest.mark.parametrize(
        ("soc", "power", "expected"),
        [
            (100.0, 0.0, "Full"),
            (99.0, 10.0, "Full"),
            (99.0, 1500.0, "Full"),
            (100.0, -1500.0, "Discharging"),
            (80.0, -1500.0, "Discharging"),
            (80.0, 1500.0, "Charging"),
            (80.0, 20.0, "Idle"),
            (50.0, -50.0, "Idle"),
        ],
    )
    def test_battery_state(self, soc, power, expected):
        fn = _lambda_for("battery_state")
        assert fn(self._battery(soc, power)) == expected

    @staticmethod
    def _night(reason="ok", survive=True, sunrise_soc=50.0, min_soc=10):
        d = MagicMock()
        d.survival_reason = reason
        d.will_survive_night = survive
        d.estimated_soc_at_sunrise = sunrise_soc
        d.battery_min_soc = min_soc
        return d

    def test_night_survival_unknown_before_first_cycle(self):
        fn = _lambda_for("night_survival_confidence")
        assert fn(self._night(reason="")) is None

    def test_night_survival_critical(self):
        fn = _lambda_for("night_survival_confidence")
        assert fn(self._night(survive=False, sunrise_soc=10.0)) == "Critical"

    def test_night_survival_warning_near_min_soc(self):
        fn = _lambda_for("night_survival_confidence")
        assert fn(self._night(sunrise_soc=12.0, min_soc=10)) == "Warning"

    def test_night_survival_warning_fires_with_high_min_soc(self):
        fn = _lambda_for("night_survival_confidence")
        assert fn(self._night(sunrise_soc=22.0, min_soc=20)) == "Warning"

    def test_night_survival_safe(self):
        fn = _lambda_for("night_survival_confidence")
        assert fn(self._night(sunrise_soc=40.0, min_soc=10)) == "Safe"


class TestPowerBalanceSensors:
    def test_net_solar_surplus_rounds(self):
        fn = _lambda_for("net_solar_surplus_w")
        d = MagicMock()
        d.net_solar_surplus_w = 1234.56
        assert fn(d) == pytest.approx(1234.6)

    def test_battery_kwh_available(self):
        fn = _lambda_for("battery_kwh_available")
        d = MagicMock()
        d.battery_soc = 50.0
        d.battery_capacity_kwh = 18.6
        assert fn(d) == pytest.approx(9.3)
        d.battery_capacity_kwh = 0.0
        assert fn(d) is None


class TestDashboardSummarySensors:
    def test_house_energy_today_sensor_was_not_duplicated(self):
        assert "house_energy_today" not in _sensor_keys()

    def test_house_load_today_is_enabled_by_default(self):
        assert _BY_KEY["house_kwh_today"].entity_registry_enabled_default is True

    def test_dashboard_uses_house_kwh_today(self):
        from tests.dashboard_support import dashboard_text, default_entity_ids

        dashboard = dashboard_text()
        assert default_entity_ids()["house_kwh_today"] in dashboard
        assert "house_energy_today" not in dashboard


class TestDailyTotalSensorsUseTotalStateClass:
    """HA raises ValueError from state_attributes when last_reset is set on a non-TOTAL sensor."""

    @staticmethod
    def _daily_totals():
        return [d for d in SENSOR_DESCRIPTIONS if d.is_daily_total]

    def test_found_daily_total_sensors(self):
        assert len(self._daily_totals()) >= 20

    def test_every_daily_total_sensor_is_state_class_total(self):
        wrong = [d.key for d in self._daily_totals() if d.state_class is not SensorStateClass.TOTAL]
        assert wrong == []

    @staticmethod
    def _sensor_with(description, **data_fields):
        data = CoordinatorData()
        data.last_reset_time = "2026-06-15T00:00:00+00:00"
        for name, value in data_fields.items():
            setattr(data, name, value)
        coordinator = SimpleNamespace(data=data, entry=SimpleNamespace(entry_id="entry"))
        return GivEnergyManagerSensor(coordinator, description)

    def test_last_reset_is_reported_for_a_total_sensor(self):
        sensor = self._sensor_with(_BY_KEY["solar_today"])
        assert sensor.last_reset == datetime(2026, 6, 15, tzinfo=timezone.utc)

    def test_last_reset_guards_on_state_class(self):
        measurement = replace(_BY_KEY["solar_today"], state_class=SensorStateClass.MEASUREMENT)
        assert self._sensor_with(measurement).last_reset is None


class TestBatteryWearFormulaAgreement:
    """Throughput counts charge plus discharge, so one rated cycle is 2 x capacity of throughput."""

    def test_life_consumed_matches_engine_cycle_cost(self):
        from custom_components.givenergy_inverter_manager.const import (
            BATTERY_RATED_CYCLES,
            CONF_BATTERY_COST,
        )
        from custom_components.givenergy_inverter_manager.core.engine import (
            _battery_cycle_cost,
        )

        capacity = 18.6
        throughput = 37.2  # one full charge plus one full discharge
        d = MagicMock()
        d.battery_capacity_kwh = capacity
        d.today.battery_throughput_kwh = throughput

        life_pct = _lambda_for("battery_life_consumed_today")(d)
        assert life_pct == pytest.approx(100 / BATTERY_RATED_CYCLES, rel=1e-3)

        cost_per_kwh = _battery_cycle_cost({CONF_BATTERY_COST: 3000.0}, capacity)
        assert cost_per_kwh * throughput == pytest.approx(3000.0 / BATTERY_RATED_CYCLES, rel=1e-6)


def test_html_attribute_is_not_recorded():
    assert GivEnergyManagerSensor._unrecorded_attributes == frozenset({"html"})


class TestSensorEntity:
    @staticmethod
    def _sensor(description, data):
        coordinator = SimpleNamespace(data=data, entry=SimpleNamespace(entry_id="entry"))
        return GivEnergyManagerSensor(coordinator, description)

    def test_a_failing_value_fn_is_reported_once_at_warning(self, caplog):
        def boom(_data):
            raise ValueError("bad reading")

        sensor = self._sensor(replace(_BY_KEY["solar_power"], value_fn=boom), CoordinatorData())
        with caplog.at_level(logging.DEBUG, logger="custom_components.givenergy_inverter_manager"):
            assert [sensor.native_value for _ in range(3)] == [None, None, None]

        records = [r for r in caplog.records if "value_fn raised" in r.getMessage()]
        assert [r.levelno for r in records] == [logging.WARNING]
        assert "solar_power" in records[0].getMessage()

    def test_each_sensor_warns_for_itself(self, caplog):
        def boom(_data):
            raise ValueError("bad reading")

        first = self._sensor(replace(_BY_KEY["solar_power"], value_fn=boom), CoordinatorData())
        second = self._sensor(replace(_BY_KEY["battery_soc"], value_fn=boom), CoordinatorData())
        with caplog.at_level(logging.WARNING, logger="custom_components.givenergy_inverter_manager"):
            assert first.native_value is None
            assert second.native_value is None
        assert len([r for r in caplog.records if "value_fn raised" in r.getMessage()]) == 2

    def test_value_comes_from_the_coordinator_data(self):
        data = CoordinatorData()
        data.solar_power_w = 1234.56
        assert self._sensor(_BY_KEY["solar_power"], data).native_value == 1234.6

    def test_no_value_before_the_first_update(self):
        assert self._sensor(_BY_KEY["solar_power"], None).native_value is None

    def test_currency_unit_falls_back_to_the_default_symbol_before_the_first_update(self):
        sensor = self._sensor(_BY_KEY["current_rate"], None)
        assert sensor.native_unit_of_measurement == DEFAULT_CURRENCY_SYMBOL

    def test_currency_unit_follows_the_configured_symbol(self):
        data = CoordinatorData()
        data.currency_symbol = "£"
        assert self._sensor(_BY_KEY["current_rate"], data).native_unit_of_measurement == "£"

    def test_html_and_attribute_functions_feed_the_state_attributes(self):
        def html(_data):
            return "<b>x</b>"

        def attrs(_data):
            return {"k": 1}

        description = replace(_BY_KEY["solar_power"], html_fn=html, attrs_fn=attrs)
        sensor = self._sensor(description, CoordinatorData())
        assert sensor.extra_state_attributes == {"html": "<b>x</b>", "k": 1}

    def test_no_state_attributes_without_html_or_attribute_functions(self):
        assert self._sensor(_BY_KEY["solar_power"], CoordinatorData()).extra_state_attributes is None


class TestEvSensorsNeedACharger:
    """A sensor that describes the EV charger is unavailable until one is discovered."""

    @pytest.mark.parametrize(
        "key",
        [
            "ev_charger_state",
            "ev_power",
            "ev_session_energy",
            "ev_draining_battery",
            "ev_protection_reason",
            "ev_charging_source",
            "ev_solar_surplus_available",
        ],
    )
    def test_unavailable_without_a_charger_and_available_with_one(self, key):
        without, with_charger = CoordinatorData(), CoordinatorData()
        with_charger.ev_available = True
        description = _BY_KEY[key]
        assert description.available_fn(without) is False
        assert description.available_fn(with_charger) is True


class TestGridToBattery:
    """The part of today's import that charged the battery, and the attributes that use it."""

    def test_is_declared_like_the_other_daily_energy_totals(self):
        description, sibling = _BY_KEY["grid_to_battery_today"], _BY_KEY["import_today"]
        assert description.native_unit_of_measurement == sibling.native_unit_of_measurement
        assert description.device_class == sibling.device_class
        assert description.state_class == sibling.state_class
        assert description.is_daily_total is True

    def test_reports_the_figure_for_today(self):
        data = CoordinatorData()
        data.today.grid_to_battery_kwh = 7.5
        assert _lambda_for("grid_to_battery_today")(data) == pytest.approx(7.5)

    def test_is_unavailable_without_the_counter(self):
        description = _BY_KEY["grid_to_battery_today"]
        data = CoordinatorData()
        data.grid_to_battery_counter_available = False
        assert description.available_fn(data) is False
        data.grid_to_battery_counter_available = True
        assert description.available_fn(data) is True

    @pytest.mark.parametrize(
        ("key", "period"),
        [
            ("self_sufficiency", "today"),
            ("self_sufficiency_yesterday", "yesterday"),
            ("self_sufficiency_this_week", "week"),
            ("self_sufficiency_this_month", "month"),
        ],
    )
    def test_each_self_sufficiency_sensor_explains_itself(self, key, period):
        data = CoordinatorData()
        acc = getattr(data, period)
        acc.house_kwh, acc.import_kwh, acc.grid_to_battery_kwh = 11.3, 12.1, 7.5
        description = _BY_KEY[key]
        assert description.value_fn(data) == pytest.approx(59.3)
        attrs = description.attrs_fn(data)
        assert set(attrs) == {
            "house_load_kwh",
            "from_grid_kwh",
            "grid_to_battery_kwh",
            "from_solar_and_battery_kwh",
            "basis",
        }
        assert attrs["from_grid_kwh"] == pytest.approx(4.6)
