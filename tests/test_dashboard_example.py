"""
Keeps docs/dashboard-example.yaml in step with the dashboard generator.

The example is the generator output for a setup with every optional feature
configured and every sensor enabled. It is a golden file: when the generator
changes on purpose, regenerate it and review the diff.

Regenerate with:
    UPDATE_DASHBOARD_EXAMPLE=1 python -m pytest tests/test_dashboard_example.py
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.dashboard_support import ENTRY_ID, FULL_CONFIG, FakeRegistry, fake_hass

_EXAMPLE = Path(__file__).parent.parent / "docs" / "dashboard-example.yaml"


def generate_example() -> str:
    from custom_components.givenergy_inverter_manager.dashboard_builder import build_dashboard_yaml

    with fake_hass(
        FULL_CONFIG,
        FakeRegistry(enable_all=True),
        ev_brand="myenergi",
    ) as hass:
        return build_dashboard_yaml(hass, ENTRY_ID)


def test_example_is_up_to_date():
    expected = generate_example()
    if os.environ.get("UPDATE_DASHBOARD_EXAMPLE"):
        _EXAMPLE.write_text(expected, encoding="utf-8")
    actual = _EXAMPLE.read_text(encoding="utf-8") if _EXAMPLE.exists() else ""
    assert actual == expected, (
        "docs/dashboard-example.yaml is out of date against dashboard.py. "
        "Run: UPDATE_DASHBOARD_EXAMPLE=1 python -m pytest tests/test_dashboard_example.py"
    )


def test_example_is_valid_yaml_with_views():
    import yaml

    parsed = yaml.safe_load(_EXAMPLE.read_text(encoding="utf-8"))
    assert [v["path"] for v in parsed["views"]]
