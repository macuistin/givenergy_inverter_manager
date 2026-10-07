"""
Pins the generated dashboard for a grid of installs, so a refactor cannot change it.

Each scenario is a config, a registry (sensors enabled or not), the Lovelace resources and
the EV charger that is present. The fixture holds a SHA-256 of the YAML for each one.
When a change to the dashboard is deliberate, regenerate and review the docs example too:

    UPDATE_DASHBOARD_MATRIX=1 python -m pytest tests/test_dashboard_matrix.py
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_FORECAST_ENTITY,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from tests.dashboard_support import (
    FULL_CONFIG,
    MINIMAL_CONFIG,
    FakeRegistry,
    dashboard_text,
    devices_of,
)
from tests.helpers import ROOT

FIXTURE = ROOT / "tests" / "golden_dashboard_matrix.json"

_PFC = "/hacsfiles/power-flow-card-plus/power-flow-card-plus.js"
_APEX = "/hacsfiles/apexcharts-card/apexcharts-card.js"

CONFIGS = {
    "minimal": MINIMAL_CONFIG,
    "full": FULL_CONFIG,
    "no_forecast": {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY},
    "immersion_sensor": {CONF_IMMERSION_TEMP_SENSOR: "sensor.t"},
    "immersion_switch": {CONF_IMMERSION_SWITCH: "switch.heater"},
}
REGISTRIES = {
    "all": lambda devices: FakeRegistry(enable_all=True, devices=devices),
    "fresh": lambda devices: FakeRegistry(devices=devices),
    "sparse": lambda devices: FakeRegistry(
        enable_all=True,
        devices=devices,
        absent={"solar_power", "battery_soc", "ev_power", "night_survival_reason", "dry_run_active"},
    ),
}
RESOURCES = {"unknown": None, "none": [], "flow": [_PFC], "apex": [_APEX], "both": [_PFC, _APEX]}
CHARGERS = {
    "no_ev": {"ev_brand": None, "states": ()},
    "myenergi": {"ev_brand": "myenergi", "states": ()},
    "wallbox": {"ev_brand": "wallbox", "states": ("sensor.wallbox_charging_power",)},
}


def scenario_ids() -> list[str]:
    grid = itertools.product(CONFIGS, REGISTRIES, RESOURCES, CHARGERS)
    return ["/".join(parts) for parts in grid]


def render_scenario(scenario: str) -> str:
    config, registry, resources, charger = scenario.split("/")
    devices = devices_of(CONFIGS[config], CHARGERS[charger]["ev_brand"])
    return dashboard_text(
        CONFIGS[config],
        REGISTRIES[registry](devices),
        resources=RESOURCES[resources],
        **CHARGERS[charger],
    )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def golden() -> dict:
    if os.environ.get("UPDATE_DASHBOARD_MATRIX"):
        fresh = {s: _digest(render_scenario(s)) for s in scenario_ids()}
        FIXTURE.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", scenario_ids())
def test_dashboard_is_unchanged(scenario, golden):
    assert _digest(render_scenario(scenario)) == golden[scenario], (
        f"The dashboard for {scenario} changed. If that is deliberate, regenerate with "
        "UPDATE_DASHBOARD_MATRIX=1 and review docs/dashboard-example.yaml."
    )


def test_the_grid_covers_the_fixture_exactly(golden):
    assert set(golden) == set(scenario_ids())
