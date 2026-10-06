"""The pre-boost export sensors are gone from the integration.

The integration never writes or advises forced battery export, so the three sensors, their
engine fields and their rule were removed. The registry clean-up is tested in
tests/ha_e2e/test_retired_sensors_e2e.py.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from custom_components.givenergy_inverter_manager.core import rules
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS
from tests.helpers import PKG

RETIRED_KEYS = (
    "pre_boost_export_recommended",
    "pre_boost_export_kwh",
    "pre_boost_export_net_gain",
)


@pytest.mark.parametrize("key", RETIRED_KEYS)
def test_sensor_is_not_created(key):
    assert key not in {d.key for d in SENSOR_DESCRIPTIONS}
    assert key not in {d.translation_key for d in SENSOR_DESCRIPTIONS}


@pytest.mark.parametrize("key", RETIRED_KEYS)
def test_coordinator_data_has_no_field_for_it(key):
    assert key not in {f.name for f in dataclasses.fields(CoordinatorData)}


@pytest.mark.parametrize("key", RETIRED_KEYS)
@pytest.mark.parametrize("path", ["strings.json", "translations/en.json", "icons.json"])
def test_no_string_or_icon_is_left(key, path):
    entities = json.loads((PKG / path).read_text(encoding="utf-8"))["entity"]
    assert key not in entities["sensor"]


def test_the_export_rule_is_gone():
    assert not hasattr(rules, "calculate_pre_boost_export_opportunity")
    assert not hasattr(rules, "PreBoostInputs")
