"""The config diet review lists every setting the wizards still ask for."""

from __future__ import annotations

import re

from custom_components.givenergy_inverter_manager.core.wizard_model import PAGE_KEYS
from tests.helpers import ROOT

DOC = ROOT / "docs" / "design" / "CONFIG_DIET.md"
DECISIONS = {"Keep", "Detect", "Fixed assumption", "Entity"}


def _rows() -> list[list[str]]:
    lines = [line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


def test_every_key_a_page_owns_has_a_row_in_the_diet():
    text = DOC.read_text(encoding="utf-8")
    owned = {key for keys in PAGE_KEYS.values() for key in keys}

    missing = sorted(key for key in owned if f"`{key}`" not in text)

    assert missing == []


def test_every_row_has_one_decision_from_the_list_and_a_reason():
    rows = _rows()

    assert rows
    for setting, page, decision, why in rows:
        assert decision in DECISIONS, setting
        assert why, setting
        assert page, setting


def test_the_follow_ups_are_a_numbered_list():
    text = DOC.read_text(encoding="utf-8")

    assert re.search(r"^## Follow-ups\n\n.*\n1\. ", text, re.S | re.M)
