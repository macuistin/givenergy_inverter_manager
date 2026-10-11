"""The recipes in docs/automations.md name entities that exist and can fire.

The entity registry of a full install is recorded in tests/ha_e2e/entity_snapshot.json, which
the e2e suite checks against the real registry, so a recipe that names an entity outside it
names an entity no install has. The battery warning once used `below: 10`, which cannot fire:
the SoC at sunrise never reads below the minimum SoC.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from custom_components.givenergy_inverter_manager.const import DEFAULT_BATTERY_MIN_SOC
from tests.helpers import ROOT

PAGE = (ROOT / "docs" / "automations.md").read_text(encoding="utf-8")
REGISTRY = {
    row["entity_id"]
    for row in json.loads((ROOT / "tests" / "ha_e2e" / "entity_snapshot.json").read_text("utf-8"))
}

_ENTITY = re.compile(r"\b[a-z_]+\.givenergy_inverter_manager_\w+")
_WITH_CHARGE = "sensor.givenergy_inverter_manager_estimated_soc_at_sunrise_with_the_planned_charge"
_WITHOUT_CHARGE = "sensor.givenergy_inverter_manager_estimated_soc_at_sunrise_without_a_charge"
_CONFIDENCE = "sensor.givenergy_inverter_manager_battery_overnight_confidence"


def _section(heading: str) -> str:
    start = PAGE.index(f"## {heading}")
    end = PAGE.find("\n---\n", start)
    return PAGE[start:end]


def _yaml_blocks(text: str) -> list:
    return [yaml.safe_load(block) for block in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)]


def test_every_entity_a_recipe_names_is_in_the_entity_registry():
    named = set(_ENTITY.findall(PAGE))
    assert named
    assert sorted(named - REGISTRY) == []


def test_the_page_names_the_entities_of_the_sunrise_recipe_from_the_registry():
    assert {_WITH_CHARGE, _CONFIDENCE} <= REGISTRY


@pytest.fixture(scope="module")
def warning():
    return _section("Alert when the battery may run flat")


def test_the_battery_warning_reads_the_figure_with_the_planned_charge(warning):
    first = _yaml_blocks(warning)[0]
    assert first["trigger"][0]["entity_id"] == _WITH_CHARGE
    assert _WITHOUT_CHARGE not in warning


def test_the_battery_warning_threshold_is_above_the_minimum_soc(warning):
    """The figure holds at the minimum SoC, so a threshold at or below it never fires."""
    thresholds = [
        item["below"]
        for block in _yaml_blocks(warning)
        for item in [*block.get("trigger", []), *block.get("condition", [])]
        if "below" in item
    ]
    assert thresholds
    assert all(below > DEFAULT_BATTERY_MIN_SOC for below in thresholds)


def test_the_battery_warning_says_to_set_the_threshold_to_your_own_level(warning):
    assert "your own comfort level" in warning


def test_the_second_trigger_option_is_the_overnight_status_with_the_charge_as_a_condition(warning):
    second = _yaml_blocks(warning)[1]
    assert second["trigger"] == [
        {"platform": "state", "entity_id": _CONFIDENCE, "to": "Critical"}
    ]
    assert second["condition"][0]["entity_id"] == _WITH_CHARGE


def test_the_page_says_why_a_threshold_at_the_minimum_could_not_fire(warning):
    assert "below: 10" in warning
    assert "could not fire" in warning
    assert "never reads below the minimum SoC" in warning
