"""
Integrity checks for sensor descriptions and translation files.

The dynamic checks run in a subprocess against the real Home Assistant package,
because the test suite stubs Home Assistant and sensor.py cannot be imported
under those stubs.
"""

from __future__ import annotations

import ast
import collections
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PKG = Path(__file__).parent.parent / "custom_components" / "givenergy_inverter_manager"
_SENSOR_TREE = ast.parse((_PKG / "sensor.py").read_text())
_JSON_FILES = ["strings.json", "translations/en.json", "icons.json"]


def _description_kwargs() -> list[dict[str, ast.expr]]:
    found = []
    for node in ast.walk(_SENSOR_TREE):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == (
            "GivEnergyManagerSensorDescription"
        ):
            found.append({kw.arg: kw.value for kw in node.keywords})
    return found


def _reject_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    duplicates = sorted(k for k, n in collections.Counter(keys).items() if n > 1)
    assert not duplicates, f"duplicate JSON keys: {duplicates}"
    return dict(pairs)


class TestStaticIntegrity:
    def test_description_keys_are_unique(self):
        keys = [kw["key"].value for kw in _description_kwargs()]
        duplicates = [k for k, n in collections.Counter(keys).items() if n > 1]
        assert duplicates == []

    @pytest.mark.parametrize("name", _JSON_FILES)
    def test_json_has_no_duplicate_keys(self, name):
        json.loads((_PKG / name).read_text(), object_pairs_hook=_reject_duplicate_keys)

    def test_every_translation_key_has_a_name(self):
        data = json.loads((_PKG / "strings.json").read_text())
        names = data["entity"]["sensor"]
        missing = sorted(
            kw["translation_key"].value
            for kw in _description_kwargs()
            if "translation_key" in kw
            and "name" not in names.get(kw["translation_key"].value, {})
            and "name" not in kw
        )
        assert missing == []


_DYNAMIC_CHECK = textwrap.dedent(
    """
    import json, sys
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, ".")
    from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES
    from custom_components.givenergy_inverter_manager import sensor as S
    from custom_components.givenergy_inverter_manager.const import DEFAULT_RATE_PERIODS
    from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
    from custom_components.givenergy_inverter_manager.core.engine import (
        CoordinatorData, RawSensorValues, build_coordinator_data)
    from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

    cfg = {"base_rate": 0.3334, "base_rate_name": "Day", "rate_periods": DEFAULT_RATE_PERIODS,
           "export_rate": 0.195, "standing_charge_per_day": 0.8259, "pso_levy_per_month": 1.46,
           "vat_rate": 9.0, "discount_rate": 5.5, "bill_start_day": 16, "currency": "EUR",
           "battery_min_soc_pct": 10, "battery_capacity_kwh": 19.0, "inverter_max_output_kw": 5.0}
    now = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    raw = RawSensorValues(solar_power_w=2000.0, battery_soc=60.0, battery_power_w=500.0,
                          grid_power_w=-300.0, house_load_w=800.0, inverter_max_w=5000.0,
                          battery_capacity_kwh=19.0)
    acc = EnergyAccumulator()
    acc.import_kwh, acc.solar_kwh, acc.house_kwh = 5.0, 8.0, 6.0
    acc.zappi_kwh, acc.zappi_cost = 3.0, 0.9
    data, _ = build_coordinator_data(raw=raw, cfg=cfg, acc=acc,
        battery_stats=BatteryStats(total_cycles=10.0), now=now,
        last_update_time=now - timedelta(minutes=5), last_soc=59.0)

    problems = []
    for label, state in (("fresh", CoordinatorData()), ("after a cycle", data)):
        for d in S.SENSOR_DESCRIPTIONS:
            try:
                d.value_fn(state)
            except Exception as err:
                problems.append(f"{d.key} ({label}): {type(err).__name__}: {err}")
    for d in S.SENSOR_DESCRIPTIONS:
        allowed = DEVICE_CLASS_STATE_CLASSES.get(d.device_class)
        if d.device_class and d.state_class and allowed is not None and d.state_class not in allowed:
            problems.append(f"{d.key}: state_class {d.state_class} invalid for {d.device_class}")
        if d.is_daily_total and d.state_class != S.SensorStateClass.TOTAL:
            problems.append(f"{d.key}: is_daily_total needs state_class TOTAL")
    print(json.dumps(problems))
    """
)


class TestAgainstRealHomeAssistant:
    def test_value_fns_and_state_classes(self):
        result = subprocess.run(
            [sys.executable, "-c", _DYNAMIC_CHECK],
            cwd=_PKG.parent.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert json.loads(result.stdout.strip().splitlines()[-1]) == []
