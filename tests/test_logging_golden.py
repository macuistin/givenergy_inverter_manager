"""
test_logging_golden.py: the exact verbose log lines, pinned over a grid of states.

The cycle block, the startup block and the GivTCP write line are compared with
tests/golden_logging.json. After a deliberate wording change, regenerate with
`UPDATE_LOGGING_GOLDEN=1 python -m pytest tests/test_logging_golden.py` and review the diff.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.givenergy_inverter_manager.discovery.ev_charger import EVChargerState
from custom_components.givenergy_inverter_manager.logging import (
    log_cycle,
    log_givtcp_write,
    log_startup,
)
from tests.test_logging import _ROOT, _enable_verbose, _make_data, _make_log, _make_raw

GOLDEN = Path(__file__).parent / "golden_logging.json"
NOW = datetime(2024, 6, 15, 14, 0, 5)

RAW_EV = {"none": {}, "plugged": {"ev_plugged_in": True, "ev_power_w": 2300.0}}
RAW_IMMERSION = {
    "off": {},
    "on_with_temp": {"immersion_on": True, "immersion_temp": 48.25},
    "off_with_temp": {"immersion_temp": 61.0},
}
RAW_FORECAST = {"none": {}, "some": {"forecast_kwh_tomorrow": 12.5}}


DATA_CHARGE = ("none", "free", "costed")
DATA_EV = {
    "absent": {},
    "charging": {
        "ev_available": True,
        "ev_charger_name": "Zappi",
        "ev_charger_state": EVChargerState.CHARGING,
        "ev_power_w": 1400.0,
        "ev_draining_battery": True,
        "ev_protection_reason": "Battery protected",
    },
    "unknown_state": {
        "ev_available": True,
        "ev_charger_name": "Zappi",
        "ev_charger_state": None,
    },
}
DATA_DRY_RUN = {"live": {}, "dry": {"dry_run": True, "dry_run_last_skipped": "Would set Zappi"}}


def _cycle_lines(caplog, raw, data) -> list[str]:
    _enable_verbose()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_ROOT):
        log_cycle(_make_log(), 7, raw, data, NOW)
    return [r.getMessage() for r in caplog.records]


def _scenarios():
    for ev, imm, fc in itertools.product(RAW_EV, RAW_IMMERSION, RAW_FORECAST):
        raw = {**RAW_EV[ev], **RAW_IMMERSION[imm], **RAW_FORECAST[fc]}
        yield f"raw/ev={ev}/immersion={imm}/forecast={fc}", raw, "free", "absent", "live"
    for charge, ev, dry in itertools.product(DATA_CHARGE, DATA_EV, DATA_DRY_RUN):
        yield f"data/charge={charge}/ev={ev}/{dry}", {}, charge, ev, dry


def _build(raw_overrides: dict, charge: str, ev: str, dry: str):
    data = _make_data(**DATA_EV[ev], **DATA_DRY_RUN[dry])
    if charge == "none":
        data.charge_decision = None
    else:
        data.charge_decision.cost_to_charge = 0.0 if charge == "free" else 1.234
    return _make_raw(**raw_overrides), data


def _startup_lines(caplog, cfg: dict) -> list[str]:
    _enable_verbose()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_ROOT):
        log_startup(_make_log(), cfg)
    return [r.getMessage() for r in caplog.records]


STARTUP_CFGS = {
    "empty": {},
    "configured": {
        "solar_power_entity": "sensor.pv",
        "battery_soc_entity": "sensor.soc",
        "immersion_switch_entity": "switch.imm",
        "target_soc_entity": "number.target",
        "base_rate": 0.3334,
        "base_rate_name": "Day",
        "rate_periods": [{"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"}],
    },
}


def _write_lines(caplog, accepted: bool) -> list[str]:
    _enable_verbose()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_ROOT):
        log_givtcp_write(_make_log(), 4, "number.target_soc", 85, "100", accepted)
    return [r.getMessage() for r in caplog.records]


def _current(caplog) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, raw_overrides, charge, ev, dry in _scenarios():
        raw, data = _build(raw_overrides, charge, ev, dry)
        out[f"cycle/{name}"] = _cycle_lines(caplog, raw, data)
    for name, cfg in STARTUP_CFGS.items():
        out[f"startup/{name}"] = _startup_lines(caplog, cfg)
    out["write/accepted"] = _write_lines(caplog, True)
    out["write/mismatch"] = _write_lines(caplog, False)
    return out


def test_verbose_log_lines_are_unchanged(caplog):
    current = _current(caplog)
    if os.environ.get("UPDATE_LOGGING_GOLDEN"):
        GOLDEN.write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n")
        pytest.skip("golden file regenerated")
    assert current == json.loads(GOLDEN.read_text())
