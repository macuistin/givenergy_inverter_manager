"""Repair issues link to the matching troubleshooting section."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import homeassistant.helpers.issue_registry as ir

from custom_components.givenergy_inverter_manager import repairs

_DOC = Path(__file__).resolve().parents[1] / "docs" / "troubleshooting.md"


def _github_anchors(markdown: str) -> set[str]:
    anchors = set()
    for line in markdown.splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if match:
            slug = re.sub(r"[^\w\- ]", "", match.group(1).lower()).replace(" ", "-")
            anchors.add(slug)
    return anchors


def _issue_keys() -> list[str]:
    return [
        value
        for name, value in vars(repairs).items()
        if name.startswith("ISSUE_") and isinstance(value, str)
    ]


def test_every_repair_issue_has_a_learn_more_url():
    assert set(repairs.LEARN_MORE_URLS) == set(_issue_keys())


def test_learn_more_anchors_exist_in_troubleshooting_doc():
    anchors = _github_anchors(_DOC.read_text(encoding="utf-8"))
    for issue, url in repairs.LEARN_MORE_URLS.items():
        base, _, fragment = url.partition("#")
        assert base == repairs.TROUBLESHOOTING_URL, issue
        assert fragment in anchors, f"{issue}: no heading for #{fragment}"


def test_created_issues_carry_learn_more_url():
    ir.async_create_issue.reset_mock()
    hass = MagicMock()

    repairs.async_create_givtcp_missing_issue(hass)
    assert (
        ir.async_create_issue.call_args.kwargs["learn_more_url"]
        == repairs.LEARN_MORE_URLS[repairs.ISSUE_GIVTCP_ENTITIES_MISSING]
    )

    repairs.async_create_min_soc_issue(hass, 45)
    assert (
        ir.async_create_issue.call_args.kwargs["learn_more_url"]
        == repairs.LEARN_MORE_URLS[repairs.ISSUE_MIN_SOC_TOO_HIGH]
    )


def test_other_charge_slots_issue_is_fixable_and_names_the_slots():
    from custom_components.givenergy_inverter_manager.discovery import ActiveChargeSlot

    ir.async_create_issue.reset_mock()
    slot = ActiveChargeSlot(2, "select.start_2", "select.end_2", "00:00", "08:00")

    repairs.async_create_other_charge_slots_issue(MagicMock(), [slot])

    kwargs = ir.async_create_issue.call_args.kwargs
    assert kwargs["is_fixable"] is True
    assert kwargs["translation_placeholders"] == {"slots": "Slot 2 (00:00 to 08:00)"}
    assert kwargs["learn_more_url"] == repairs.LEARN_MORE_URLS[repairs.ISSUE_OTHER_CHARGE_SLOTS_ACTIVE]
