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

import pytest

from tests.helpers import PKG

_PKG = PKG
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
        )
        assert missing == []

    def test_translated_sensors_do_not_repeat_the_name_in_code(self):
        repeated = sorted(
            kw["key"].value
            for kw in _description_kwargs()
            if "translation_key" in kw and "name" in kw
        )
        assert repeated == []


def _literal_kwarg(kwargs: dict[str, ast.expr], name: str):
    node = kwargs.get(name)
    return None if node is None else ast.literal_eval(node)


_PERIOD_KEYS = {
    "week": {
        "solar_this_week",
        "import_this_week",
        "export_this_week",
        "import_cost_this_week",
        "export_earnings_this_week",
        "import_kwh_cheap_this_week",
        "import_kwh_peak_this_week",
        "immersion_savings_this_week",
    },
    "month": {
        "accrued_bill",
        "solar_this_month",
        "import_this_month",
        "export_this_month",
        "import_cost_this_month",
        "export_earnings_this_month",
        "import_kwh_cheap_this_month",
        "import_kwh_peak_this_month",
        "immersion_savings_this_month",
        "net_position_this_month",
    },
    "year": {"solar_this_year", "export_this_year", "export_earnings_this_year"},
}


class TestResetPeriods:
    def test_week_month_and_year_sensors_declare_their_reset_period(self):
        declared: dict[str, set[str]] = collections.defaultdict(set)
        for kw in _description_kwargs():
            period = _literal_kwarg(kw, "reset_period")
            if period:
                declared[period].add(kw["key"].value)
        assert dict(declared) == _PERIOD_KEYS

    def test_period_names_are_known(self):
        periods = {_literal_kwarg(kw, "reset_period") for kw in _description_kwargs()}
        assert periods <= {None, "day", "week", "month", "year"}

    def test_yesterday_and_trailing_sensors_have_no_total_state_class(self):
        wrong = [
            kw["key"].value
            for kw in _description_kwargs()
            if kw["key"].value.endswith(("_yesterday", "_trailing_12m"))
            and getattr(kw.get("state_class"), "attr", None) in ("TOTAL", "TOTAL_INCREASING")
        ]
        assert wrong == []


_DYNAMIC_CHECK = textwrap.dedent(
    """
    import json, sys
    from types import SimpleNamespace
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, ".")
    from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES
    from custom_components.givenergy_inverter_manager import sensor as S
    from custom_components.givenergy_inverter_manager.const import DEFAULT_RATE_PERIODS
    from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
    from custom_components.givenergy_inverter_manager.core.engine import (
        CoordinatorData, RawSensorValues)
    from tests.core.flat_engine import build_coordinator_data
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
    MONOTONIC_TOTALS = {"battery_cycles", "register_write_count"}
    starts = {
        "last_reset_time": datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
        "week_start_time": datetime(2026, 6, 8, tzinfo=timezone.utc).isoformat(),
        "month_start_time": datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
        "year_start_time": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    }
    for name, value in starts.items():
        setattr(data, name, value)
    expected_start = {
        "day": datetime.fromisoformat(starts["last_reset_time"]),
        "week": datetime.fromisoformat(starts["week_start_time"]),
        "month": datetime.fromisoformat(starts["month_start_time"]),
        "year": datetime.fromisoformat(starts["year_start_time"]),
    }
    coordinator = SimpleNamespace(data=data, entry=SimpleNamespace(entry_id="entry"))
    for d in S.SENSOR_DESCRIPTIONS:
        period = S.reset_period_of(d)
        total = d.state_class == S.SensorStateClass.TOTAL
        if period is not None and not total:
            problems.append(f"{d.key}: reset period {period} needs state_class TOTAL")
        if period is None and total and d.key not in MONOTONIC_TOTALS:
            problems.append(f"{d.key}: state_class TOTAL without a reset period or last_reset")
        last_reset = S.GivEnergyManagerSensor(coordinator, d).last_reset
        if period is not None and total and last_reset != expected_start[period]:
            problems.append(f"{d.key}: last_reset {last_reset} is not the {period} start")
        if (period is None or not total) and last_reset is not None:
            problems.append(f"{d.key}: reports last_reset without a resetting TOTAL class")
        if d.key.endswith(("_yesterday", "_trailing_12m")) and d.state_class in (
            S.SensorStateClass.TOTAL, S.SensorStateClass.TOTAL_INCREASING,
        ):
            problems.append(f"{d.key}: not cumulative, state_class must not be a total")
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
