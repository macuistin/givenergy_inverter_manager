"""
stored_dashboard.py - decisions about the storage dashboard the integration keeps current.

The user picks a storage-mode dashboard and runs update_dashboard, or presses Fix on the repair.
The integration then writes the generated dashboard into it and remembers its URL path. Nothing
is written without that click. These functions decide which dashboard a call means, whether it
may be written, and what the out-of-date repair should do. They take plain values, so the Home
Assistant side (services.py, stored_dashboard.py) only gathers the facts and acts on the answer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Refusal(StrEnum):
    """Why a dashboard cannot be written. Each value is a translation key in strings.json."""

    NO_URL_PATH = "dashboard_url_path_missing"
    NOT_FOUND = "dashboard_not_found"
    NOT_STORAGE = "dashboard_not_storage"
    RECOVERY_MODE = "dashboard_recovery_mode"


class DashboardRefused(Exception):
    """The dashboard a call names cannot be written."""

    def __init__(self, refusal: Refusal, url_path: str = "") -> None:
        super().__init__(refusal.value)
        self.refusal = refusal
        self.url_path = url_path


@dataclass(frozen=True)
class DashboardFacts:
    """What Home Assistant says about one dashboard URL path.

    *config* is the saved configuration, or None while the dashboard has none yet (a new
    dashboard from scratch is auto-generated until it is first saved).
    """

    exists: bool
    storage_mode: bool = False
    config: Mapping[str, Any] | None = None


class IssueAction(StrEnum):
    """What the out-of-date check does with the repair."""

    RAISE = "raise"
    CLEAR = "clear"
    FORGET = "forget"  # clear the repair and forget the remembered URL path


def choose_url_path(given: str | None, remembered: str | None) -> str:
    """The URL path a call means: the one it names, else the one remembered."""
    for candidate in (given, remembered):
        if candidate and candidate.strip():
            return candidate.strip().strip("/")
    raise DashboardRefused(Refusal.NO_URL_PATH)


def ensure_writable(url_path: str, facts: DashboardFacts, *, recovery_mode: bool) -> None:
    """Raise DashboardRefused unless the dashboard at *url_path* can take the generated config.

    A storage dashboard with no config yet is writable. A YAML dashboard is not, because its
    configuration is a file the user owns.
    """
    if recovery_mode:
        raise DashboardRefused(Refusal.RECOVERY_MODE, url_path)
    if not facts.exists:
        raise DashboardRefused(Refusal.NOT_FOUND, url_path)
    if not facts.storage_mode:
        raise DashboardRefused(Refusal.NOT_STORAGE, url_path)


def as_stored(config: Mapping[str, Any]) -> dict[str, Any]:
    """*config* as the storage file holds it after a restart: plain JSON types only.

    Tuples become lists and keys become strings, so a config compared before and after a
    restart reads the same.
    """
    return json.loads(json.dumps(config, default=str))


def configs_match(stored: Mapping[str, Any] | None, generated: Mapping[str, Any]) -> bool:
    """True when the saved dashboard is exactly the generated one."""
    return stored is not None and as_stored(stored) == as_stored(generated)


def issue_action(
    remembered: str | None, facts: DashboardFacts, generated: Mapping[str, Any]
) -> IssueAction:
    """Raise the repair while the remembered dashboard differs from the generated one.

    A dashboard that is gone, or is no longer a storage dashboard, cannot be updated, so it is
    forgotten. With nothing remembered there is nothing to keep current.
    """
    if not remembered:
        return IssueAction.CLEAR
    if not (facts.exists and facts.storage_mode):
        return IssueAction.FORGET
    if configs_match(facts.config, generated):
        return IssueAction.CLEAR
    return IssueAction.RAISE
