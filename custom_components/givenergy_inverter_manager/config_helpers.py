"""
config_helpers.py — Small helpers for reading a config entry.

Kept free of config-flow imports so the flow, the coordinator and the dashboard code can
all use the same merge rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def effective_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry values in force: saved options over setup data.

    A key whose value is None is treated as unset, so it never hides a value from the
    other source. A falsy value that is not None (0, an empty string, an empty list) is
    a real choice and wins.
    """
    values = {k: v for k, v in entry.data.items() if v is not None}
    values.update({k: v for k, v in entry.options.items() if v is not None})
    return values
