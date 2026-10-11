"""
config_helpers.py — Small helpers for reading a config entry.

Kept free of config-flow imports so the flow, the coordinator and the dashboard code can
all use the same merge rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def merge_config(data: Mapping[str, Any], options: Mapping[str, Any]) -> dict[str, Any]:
    """Return *data* with *options* over it, the rule effective_config applies to an entry.

    A key whose value is None is treated as unset, so it never hides a value from the
    other source. A falsy value that is not None (0, an empty string, an empty list) is
    a real choice and wins.
    """
    values = {k: v for k, v in data.items() if v is not None}
    values.update({k: v for k, v in options.items() if v is not None})
    return values


def effective_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry values in force: saved options over setup data."""
    return merge_config(entry.data, entry.options)
