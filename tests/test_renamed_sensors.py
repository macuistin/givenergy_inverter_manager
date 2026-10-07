"""The base rate import sensors say base rate, and kept their keys.

No peak band is configured: these sensors count import made while no timed rate period is
active, which is the base rate. Only the display names changed. The key is the unique ID, so
history and statistics stay with the sensor. docs/sensors.md lists the old names under
"Renamed sensors".
"""

from __future__ import annotations

import importlib.util
import json

import pytest

from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS
from tests.helpers import PKG, ROOT


@pytest.fixture(scope="module")
def renamed():
    spec = importlib.util.spec_from_file_location(
        "gen_sensor_docs", ROOT / "scripts" / "gen_sensor_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RENAMED_SENSORS


def _names(path: str) -> dict[str, str]:
    sensors = json.loads((PKG / path).read_text(encoding="utf-8"))["entity"]["sensor"]
    return {key: value["name"] for key, value in sensors.items() if "name" in value}


def test_the_renamed_sensors_are_the_peak_keyed_ones(renamed):
    keys = {key for key, _, _ in renamed}
    assert keys == {
        "import_kwh_peak_today",
        "import_kwh_peak_yesterday",
        "import_kwh_peak_this_week",
        "import_kwh_peak_this_month",
        "import_cost_peak_today",
        "peak_import_fraction_today",
    }


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
def test_each_sensor_shows_its_new_name(renamed, path):
    names = _names(path)
    for key, _old, new in renamed:
        assert names[key] == new


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
def test_no_name_says_peak_rate_any_more(path):
    assert [name for name in _names(path).values() if "peak rate" in name.lower()] == []


def test_the_keys_and_translation_keys_did_not_change(renamed):
    by_key = {d.key: d for d in SENSOR_DESCRIPTIONS}
    for key, _old, _new in renamed:
        assert by_key[key].translation_key == key


def test_the_docs_list_the_previous_names(renamed):
    page = (ROOT / "docs" / "sensors.md").read_text(encoding="utf-8")
    assert "## Renamed sensors" in page
    for key, old, new in renamed:
        assert f"| `{key}` | {old} | {new} |" in page
