"""
active_repairs.py: read this integration's open repair issues for the Active Repairs sensor.

An issue counts while it is active and the user has not ignored it (no dismissed version).
Its title is read from the issue translations for Home Assistant's language, with the issue's
placeholders filled, and falls back to the issue id. The formatting lives in
core/repair_summary.py.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import translation

from .const import DOMAIN
from .core.repair_summary import RepairIssue, issue_title


def _counts(issue: ir.IssueEntry) -> bool:
    return issue.domain == DOMAIN and issue.active and issue.dismissed_version is None


def _repair(issue: ir.IssueEntry, titles: Mapping[str, str]) -> RepairIssue:
    template = titles.get(f"component.{DOMAIN}.issues.{issue.translation_key}.title")
    return RepairIssue(
        issue_id=issue.issue_id,
        title=issue_title(template, issue.translation_placeholders, issue.issue_id),
        severity=str(issue.severity) if issue.severity else "",
        fixable=bool(issue.is_fixable),
    )


async def async_active_repairs(hass: HomeAssistant) -> tuple[RepairIssue, ...]:
    """This integration's open repair issues that the user has not ignored, oldest first."""
    issues = [i for i in ir.async_get(hass).issues.values() if _counts(i)]
    if not issues:
        return ()
    titles = await translation.async_get_translations(
        hass, hass.config.language, "issues", [DOMAIN]
    )
    return tuple(_repair(issue, titles) for issue in issues)


@callback
def _is_ours(event_data: Mapping) -> bool:
    return event_data.get("domain") == DOMAIN


@callback
def async_listen_repairs(hass: HomeAssistant, on_change: Callable[[Event], None]) -> CALLBACK_TYPE:
    """Call the @callback on_change whenever an issue of this integration changes."""
    return hass.bus.async_listen(
        ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, on_change, event_filter=_is_ours
    )
