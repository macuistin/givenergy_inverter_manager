"""Pins the HTML and state strings of every report.

golden_reporting.json was generated from reporting.py before its long builders were split
into section helpers. "digests" holds one hash per engine case in golden_engine_snapshots.json
(all six reports, plus the plan without a decision). "handmade" holds 80 hand-built
CoordinatorData values that hit the accuracy, peak-import, savings and no-decision branches.
"readable" keeps the full text of four cases so a failure can be diffed by eye.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.core.reporting_snapshot import digest, render_all, render_handmade

_HERE = Path(__file__).parent
_GOLDEN = json.loads((_HERE / "golden_reporting.json").read_text())
_ENGINE_CASES = json.loads((_HERE / "golden_engine_snapshots.json").read_text())["cases"]


@pytest.mark.parametrize("index", range(len(_GOLDEN["digests"])))
def test_engine_case_reports_are_unchanged(index):
    assert digest(render_all(_ENGINE_CASES[index])) == _GOLDEN["digests"][index]


@pytest.mark.parametrize("index", range(len(_GOLDEN["handmade"])))
def test_handmade_reports_are_unchanged(index):
    entry = _GOLDEN["handmade"][index]
    assert digest(render_handmade(entry["spec"])) == entry["digest"]


@pytest.mark.parametrize("key", sorted(_GOLDEN["readable"]))
def test_readable_reports_are_unchanged(key):
    index = int(key.split(":")[1])
    assert render_all(_ENGINE_CASES[index]) == _GOLDEN["readable"][key]
