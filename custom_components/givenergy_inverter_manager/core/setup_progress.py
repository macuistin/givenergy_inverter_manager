"""
setup_progress.py - the checklist of what is left to set up, and whether the required part is done.

The dashboard shows the checklist until the required items are done, and hides it after. There
is no dismiss button: a required item is either done or not. Optional items (hot water, an EV
charger) never hold the checklist open. They are listed once as available while they are not set.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_IMMERSION_SWITCH,
    CONF_RATE_PERIODS,
)
from .tariff import build_tariff

STATE_COMPLETE = "complete"
STATE_INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class SetupFacts:
    """What the coordinator knows that the saved config does not say."""

    inverter_found: bool
    forecast_readable: bool
    ev_charger_found: bool
    dry_run: bool
    # A test instance holds dry run on for good, so turning it off is not a step it can take.
    test_instance: bool


@dataclass(frozen=True)
class SetupItem:
    """One line of the checklist."""

    key: str
    label: str
    done: bool
    required: bool

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "done": self.done, "required": self.required}


def _is_set(config: Mapping[str, Any], key: str) -> bool:
    return config.get(key) not in (None, "")


def _has_timed_rate(config: Mapping[str, Any]) -> bool:
    """True when a timed rate period is saved and valid. The built-in defaults do not count."""
    return bool(config.get(CONF_RATE_PERIODS)) and bool(build_tariff(dict(config)).rate_periods)


def setup_items(config: Mapping[str, Any], facts: SetupFacts) -> tuple[SetupItem, ...]:
    """The checklist for this merged config and these readings, required items first."""
    tariff_set = _is_set(config, CONF_BASE_RATE) and _is_set(config, CONF_EXPORT_RATE)
    forecast_set = _is_set(config, CONF_FORECAST_ENTITY) and facts.forecast_readable
    return (
        SetupItem("inverter", "Inverter found", facts.inverter_found, True),
        SetupItem("tariff", "Tariff set", tariff_set, True),
        SetupItem("cheap_window", "Cheap rate window set", _has_timed_rate(config), True),
        SetupItem("forecast", "Solar forecast added", forecast_set, True),
        SetupItem("dry_run", "Dry run turned off", not facts.dry_run, not facts.test_instance),
        SetupItem("hot_water", "Hot water", _is_set(config, CONF_IMMERSION_SWITCH), False),
        SetupItem("ev_charger", "EV charger", facts.ev_charger_found, False),
    )


def setup_state(items: tuple[SetupItem, ...]) -> str:
    """complete when every required item is done, else incomplete. With no items yet: incomplete."""
    if not items:
        return STATE_INCOMPLETE
    done = all(item.done for item in items if item.required)
    return STATE_COMPLETE if done else STATE_INCOMPLETE
