"""
discovery/givtcp.py: the entity ids of the rate sensors GivTCP holds.

The rest of the GivTCP discovery lives in inverter/givtcp/discovery.py. This module goes when
the rate comparison is removed (card RA1).
"""

from __future__ import annotations

from ..inverter.givtcp.discovery import GIVTCP_PREFIX

# ── Rates GivTCP holds ───────────────────────────────────────────────────────

# GivTCP keeps its own day, night and export rates as sensors named by the inverter serial.
GIVTCP_RATE_SUFFIXES: dict[str, str] = {
    "day": "_day_rate",
    "night": "_night_rate",
    "export": "_export_rate",
}


def givtcp_rate_entity_ids(serial: str) -> dict[str, str]:
    """The entity ids of GivTCP's day, night and export rate sensors for this inverter."""
    return {
        name: f"sensor.{GIVTCP_PREFIX}{serial}{suffix}"
        for name, suffix in GIVTCP_RATE_SUFFIXES.items()
    }
