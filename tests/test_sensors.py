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
