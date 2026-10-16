"""
repair_summary.py: this integration's open repairs, as the Active Repairs sensor shows them.

active_repairs.py reads Home Assistant's issue registry and the translated titles, and hands
the open issues here. This module fills a title's placeholders and writes the markdown summary
the dashboard shows, one bold line per issue and a link to the Repairs page.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..const import REPAIRS_PATH

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
OPEN_REPAIRS_LINK = f"[Open Repairs]({REPAIRS_PATH})"


@dataclass(frozen=True)
class RepairIssue:
    """One open repair issue of this integration, with its title already translated."""

    issue_id: str
    title: str
    severity: str
    fixable: bool

    def as_attribute(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "severity": self.severity,
            "fixable": self.fixable,
        }


def fill_placeholders(template: str, placeholders: Mapping[str, str] | None) -> str:
    """The template with each {name} it has a value for replaced. Others are left as they are."""
    values = placeholders or {}
    return _PLACEHOLDER.sub(lambda m: str(values.get(m[1], m[0])), template)


def issue_title(template: str | None, placeholders: Mapping[str, str] | None, issue_id: str) -> str:
    """The translated title with its placeholders filled, or the issue id when there is none."""
    if not template:
        return issue_id
    return fill_placeholders(template, placeholders)


def repairs_summary(issues: Sequence[RepairIssue]) -> str:
    """One bold line per issue and a link to the Repairs page, or empty text when none is open."""
    if not issues:
        return ""
    lines = [f"- **{issue.title}**" for issue in issues]
    return "\n".join([*lines, OPEN_REPAIRS_LINK])
