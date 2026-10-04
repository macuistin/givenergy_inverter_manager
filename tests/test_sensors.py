"""
Tests for sensor entity descriptions.

Uses AST analysis to validate sensor keys, metadata, and value_fn lambdas
without importing sensor.py (which fails under conftest stubs because
SensorEntityDescription is replaced with `object`).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SENSOR_PY = (
    Path(__file__).parent.parent / "custom_components" / "givenergy_inverter_manager" / "sensor.py"
)
_TREE = ast.parse(_SENSOR_PY.read_text())


def _sensor_keys() -> set[str]:
    """All key= values in SENSOR_DESCRIPTIONS."""
    keys = set()
    for node in ast.walk(_TREE):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    keys.add(kw.value.value)
    return keys


def _sensor_kwarg(key: str, attr: str) -> str | None:
    """Return the Attribute.attr (or Constant value) of a kwarg for the given sensor key."""
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        has_key = any(
            kw.arg == "key" and isinstance(kw.value, ast.Constant) and kw.value.value == key
            for kw in node.keywords
        )
        if not has_key:
            continue
        for kw in node.keywords:
            if kw.arg != attr:
                continue
            if isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
            if isinstance(kw.value, ast.Attribute):
                return kw.value.attr  # e.g. SensorStateClass.MEASUREMENT → "MEASUREMENT"
    return None


def _value_fn_source(key: str) -> str | None:
    """Return the source text of the value_fn lambda for the given sensor key."""
    src = _SENSOR_PY.read_text()
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        has_key = any(
            kw.arg == "key" and isinstance(kw.value, ast.Constant) and kw.value.value == key
            for kw in node.keywords
        )
        if not has_key:
            continue
        for kw in node.keywords:
            if kw.arg == "value_fn" and isinstance(kw.value, ast.Lambda):
                # Extract source text using line/col offsets
                lines = src.splitlines()
                lam = kw.value
                start_line = lam.lineno - 1
                line = lines[start_line]
                return line[lam.col_offset :].split("\n")[0].strip().rstrip(",")
    return None


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
    """battery_power must be a watts power sensor — the power-flow-card depends on it."""

    def test_unit_is_watt(self):
        unit = _sensor_kwarg("battery_power", "native_unit_of_measurement")
        assert unit is not None, "native_unit_of_measurement not set on battery_power"
        assert "WATT" in unit.upper() or unit == "W", (
            f"battery_power unit should be watts, got {unit!r}"
        )

    def test_device_class_is_power(self):
        dc = _sensor_kwarg("battery_power", "device_class")
        assert dc is not None, "device_class not set on battery_power"
        assert "POWER" in dc.upper(), f"battery_power device_class should be POWER, got {dc!r}"

    def test_state_class_is_measurement(self):
        sc = _sensor_kwarg("battery_power", "state_class")
        assert sc is not None, "state_class not set on battery_power"
        assert "MEASUREMENT" in sc.upper(), (
            f"battery_power state_class should be MEASUREMENT, got {sc!r}"
        )


class TestBatteryPowerValueFn:
    """value_fn lambda must read battery_power_w, not some other attribute."""

    def test_references_battery_power_w(self):
        src = _value_fn_source("battery_power")
        assert src is not None, "value_fn not found for battery_power"
        assert "battery_power_w" in src, (
            f"value_fn for battery_power should access d.battery_power_w, got: {src!r}"
        )

    def test_does_not_reference_battery_soc(self):
        src = _value_fn_source("battery_power")
        assert src is not None
        assert "battery_soc" not in src, (
            f"value_fn for battery_power must not read battery_soc: {src!r}"
        )

    def test_lambda_is_callable_charging(self):
        """Eval the lambda with a mock object to confirm it returns the right value."""
        from unittest.mock import MagicMock

        src = _value_fn_source("battery_power")
        assert src is not None
        fn = eval(src)  # noqa: S307 — test only, evaluating our own source
        d = MagicMock()
        d.battery_power_w = 2500.0
        assert fn(d) == pytest.approx(2500.0)

    def test_lambda_is_callable_discharging(self):
        from unittest.mock import MagicMock

        fn = eval(_value_fn_source("battery_power"))  # noqa: S307
        d = MagicMock()
        d.battery_power_w = -1800.0
        assert fn(d) == pytest.approx(-1800.0)

    def test_lambda_rounds_to_one_decimal(self):
        from unittest.mock import MagicMock

        fn = eval(_value_fn_source("battery_power"))  # noqa: S307
        d = MagicMock()
        d.battery_power_w = 2500.456
        assert fn(d) == pytest.approx(2500.5)


class TestGridPowerMetadata:
    def test_device_class_is_power(self):
        assert "POWER" in _sensor_kwarg("grid_power", "device_class").upper()

    def test_unit_is_watt(self):
        assert "WATT" in _sensor_kwarg("grid_power", "native_unit_of_measurement").upper()

    def test_state_class_is_measurement(self):
        assert "MEASUREMENT" in _sensor_kwarg("grid_power", "state_class").upper()


class TestImmersionPowerMetadata:
    """immersion_power must be a watts sensor reading data.immersion_load_w."""

    def test_sensor_declared(self):
        assert "immersion_power" in _sensor_keys()

    def test_unit_is_watt(self):
        unit = _sensor_kwarg("immersion_power", "native_unit_of_measurement")
        assert unit is not None and "WATT" in unit.upper()

    def test_device_class_is_power(self):
        dc = _sensor_kwarg("immersion_power", "device_class")
        assert dc is not None and "POWER" in dc.upper()

    def test_state_class_is_measurement(self):
        sc = _sensor_kwarg("immersion_power", "state_class")
        assert sc is not None and "MEASUREMENT" in sc.upper()

    def test_value_fn_uses_immersion_load_w(self):
        src = _value_fn_source("immersion_power")
        assert src is not None and "immersion_load_w" in src

    def test_lambda_on_when_running(self):
        from unittest.mock import MagicMock

        fn = eval(_value_fn_source("immersion_power").rstrip(","))  # noqa: S307
        d = MagicMock()
        d.immersion_load_w = 3000.0
        assert fn(d) == pytest.approx(3000.0)

    def test_lambda_off_is_zero(self):
        from unittest.mock import MagicMock

        fn = eval(_value_fn_source("immersion_power").rstrip(","))  # noqa: S307
        d = MagicMock()
        d.immersion_load_w = 0.0
        assert fn(d) == pytest.approx(0.0)


class TestWeeklyMonthlySensorStateClass:
    """Weekly and monthly sensors must use TOTAL not TOTAL_INCREASING.
    They can decrease from floating-point rounding, causing recorder warnings."""

    def test_weekly_sensors_use_total_not_total_increasing(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/sensor.py").read_text()
        # Find the weekly section
        weekly_start = src.find("# ── Weekly accumulations")
        assert weekly_start != -1
        weekly_section = src[weekly_start:]
        assert "TOTAL_INCREASING" not in weekly_section, (
            "Weekly/monthly sensors must use SensorStateClass.TOTAL not TOTAL_INCREASING — "
            "float rounding can cause micro-decreases that trigger HA recorder warnings."
        )


def _lambda_for(key: str):
    """Compile the full (possibly multi-line) value_fn lambda for the given sensor key."""
    src = _SENSOR_PY.read_text()
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        if not any(
            kw.arg == "key" and isinstance(kw.value, ast.Constant) and kw.value.value == key
            for kw in node.keywords
        ):
            continue
        for kw in node.keywords:
            if kw.arg == "value_fn":
                from custom_components.givenergy_inverter_manager import const

                return eval(  # noqa: S307
                    f"({ast.get_source_segment(src, kw.value)})", dict(vars(const))
                )
    raise AssertionError(f"value_fn not found for {key}")


class TestThroughputBudgetSensors:
    """Budget sensors are disabled diagnostics that read the engine fields."""

    def test_pct_sensor_state_class_is_measurement(self):
        assert _sensor_kwarg("battery_throughput_budget_pct", "state_class") == "MEASUREMENT"

    def test_pct_value_fn_rounds_and_handles_none(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("battery_throughput_budget_pct")
        d = MagicMock()
        d.battery_throughput_budget_pct = 83.456
        assert fn(d) == pytest.approx(83.5)
        d.battery_throughput_budget_pct = None
        assert fn(d) is None

    def test_status_value_fn_returns_none_when_unset(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("battery_throughput_budget_status")
        d = MagicMock()
        d.battery_throughput_budget_status = ""
        assert fn(d) is None
        d.battery_throughput_budget_status = "High"
        assert fn(d) == "High"


class TestBatteryYearsRemainingSensor:
    def test_value_fn_rounds_and_handles_none(self):
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

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
        assert _sensor_kwarg(key, "state_class") == "MEASUREMENT"


class TestEfficiencySensors:
    @pytest.mark.parametrize(
        ("key", "period"),
        [
            ("cheap_import_fraction_this_week", "week"),
            ("cheap_import_fraction_this_month", "month"),
        ],
    )
    def test_cheap_import_fraction(self, key, period):
        from unittest.mock import MagicMock

        fn = _lambda_for(key)
        d = MagicMock()
        acc = getattr(d, period)
        acc.cheap_import_fraction = 0.625
        acc.import_kwh = 8.0
        assert fn(d) == pytest.approx(62.5)
        acc.import_kwh = 0.0
        assert fn(d) is None

    def test_roundtrip_efficiency_value(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("battery_roundtrip_efficiency_today")
        d = MagicMock()
        d.today.battery_charge_kwh = 10.0
        d.today.battery_discharge_kwh = 9.2
        assert fn(d) == pytest.approx(92.0)
        d.today.battery_charge_kwh = 0.0
        assert fn(d) is None

    def test_roundtrip_efficiency_is_not_a_daily_total(self):
        for node in ast.walk(_TREE):
            if isinstance(node, ast.Call) and any(
                kw.arg == "key"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "battery_roundtrip_efficiency_today"
                for kw in node.keywords
            ):
                assert not any(kw.arg == "is_daily_total" for kw in node.keywords), (
                    "MEASUREMENT sensors must not set last_reset"
                )


class TestNextCheapRateSensors:
    def test_start_shows_time_when_known(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = "23:00"
        d.hours_to_cheap_rate = 9.0
        assert fn(d) == "23:00"

    def test_start_shows_now_when_active(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = None
        d.hours_to_cheap_rate = 0.0
        assert fn(d) == "Now"

    def test_start_is_none_on_flat_tariff(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("next_cheap_rate_start")
        d = MagicMock()
        d.next_cheap_rate_start = None
        d.hours_to_cheap_rate = None
        assert fn(d) is None

    def test_hours_value_fn(self):
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

        fn = _lambda_for(key)
        d = MagicMock()
        setattr(getattr(d, section), attr, 4.56789)
        assert fn(d) == pytest.approx(4.568)

    @pytest.mark.parametrize(
        "key", ["battery_charge_kwh_today", "battery_discharge_kwh_today", "house_kwh_today"]
    )
    def test_daily_energy_sensors_are_total(self, key):
        assert _sensor_kwarg(key, "state_class") == "TOTAL"


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
        from unittest.mock import MagicMock

        fn = _lambda_for("battery_power_direction")
        d = MagicMock()
        d.battery_power_w = power_w
        assert fn(d) == expected

    def test_days_in_period_value_fn(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("days_in_period")
        d = MagicMock()
        d.days_in_period = 12
        assert fn(d) == 12

    def test_integration_version_matches_manifest(self):
        import json

        from custom_components.givenergy_inverter_manager.const import INTEGRATION_VERSION

        manifest = _SENSOR_PY.parent / "manifest.json"
        assert json.loads(manifest.read_text())["version"] == INTEGRATION_VERSION


class TestEvKmSensors:
    def test_km_value_fn(self):
        from unittest.mock import MagicMock

        d = MagicMock()
        d.ev_km_charged_today = 42.5
        assert _lambda_for("ev_km_charged_today")(d) == 42.5

    def test_cost_per_km_value_fn(self):
        from unittest.mock import MagicMock

        d = MagicMock()
        d.ev_cost_per_km_today = None
        assert _lambda_for("ev_cost_per_km_today")(d) is None

    def test_cost_per_km_is_not_a_daily_total(self):
        for node in ast.walk(_TREE):
            if isinstance(node, ast.Call) and any(
                kw.arg == "key"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "ev_cost_per_km_today"
                for kw in node.keywords
            ):
                assert not any(kw.arg == "is_daily_total" for kw in node.keywords)


class TestDerivedSensors:
    def test_solar_capture_excludes_missed_solar_once(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 20.0
        d.today.missed_solar_kwh = 5.0
        assert fn(d) == pytest.approx(75.0)

    def test_solar_capture_full_when_nothing_missed(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 12.0
        d.today.missed_solar_kwh = 0.0
        assert fn(d) == pytest.approx(100.0)

    def test_solar_capture_never_negative(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 4.0
        d.today.missed_solar_kwh = 6.0
        assert fn(d) == pytest.approx(0.0)

    def test_solar_capture_none_without_solar(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_capture_efficiency_today")
        d = MagicMock()
        d.today.solar_kwh = 0.0
        d.today.missed_solar_kwh = 0.0
        assert fn(d) is None

    def test_solar_capture_is_not_a_daily_total(self):
        for node in ast.walk(_TREE):
            if isinstance(node, ast.Call) and any(
                kw.arg == "key"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "solar_capture_efficiency_today"
                for kw in node.keywords
            ):
                assert not any(kw.arg == "is_daily_total" for kw in node.keywords)

    def test_usable_capacity_scales_with_remaining_life(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("battery_usable_capacity_kwh")
        d = MagicMock()
        d.battery_capacity_kwh = 10.0
        d.battery_stats.estimated_remaining_life_pct = 90.0
        assert fn(d) == pytest.approx(9.0)
        d.battery_capacity_kwh = 0.0
        assert fn(d) is None

    def test_net_position_this_month_rounds(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("net_position_this_month")
        d = MagicMock()
        d.month.net_position = 3.141592
        assert fn(d) == pytest.approx(3.1416)


class TestCheapestRateSensors:
    def test_zero_rate_is_reported(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.0
        d.cheapest_rate_name = "Free hour"
        assert fn(d) == 0.0

    def test_none_before_first_cycle(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.0
        d.cheapest_rate_name = ""
        assert fn(d) is None

    def test_rate_rounds_to_four_places(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("cheapest_rate")
        d = MagicMock()
        d.cheapest_rate = 0.096512
        d.cheapest_rate_name = "Nightboost"
        assert fn(d) == pytest.approx(0.0965)

    def test_period_name(self):
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

        fn = _lambda_for(key)
        d = MagicMock()
        setattr(d, attr, True)
        assert fn(d) == "yes"
        setattr(d, attr, False)
        assert fn(d) == "no"


class TestPeriodTimeSensors:
    def test_minutes_remaining_passthrough(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("minutes_remaining_in_period")
        d = MagicMock()
        d.minutes_remaining_in_period = 60.0
        assert fn(d) == 60.0
        d.minutes_remaining_in_period = None
        assert fn(d) is None

    def test_rate_saving_reports_zero_at_base_rate(self):
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

        fn = _lambda_for("grid_power_direction")
        d = MagicMock()
        d.grid_power_w = grid_w
        assert fn(d) == expected

    def test_solar_pct_of_max(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_power_pct_of_max")
        d = MagicMock()
        d.solar_power_w = 2500.0
        d.inverter_max_w = 5000.0
        assert fn(d) == pytest.approx(50.0)

    def test_solar_pct_of_max_none_without_inverter_limit(self):
        from unittest.mock import MagicMock

        fn = _lambda_for("solar_power_pct_of_max")
        d = MagicMock()
        d.solar_power_w = 2500.0
        d.inverter_max_w = 0.0
        assert fn(d) is None


class TestStatusSensors:
    @staticmethod
    def _battery(soc, power):
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

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
