"""
default_enabled.py - the sensors that became enabled by default after they were first shipped.

Home Assistant applies a sensor's enabled default only when it creates the entity, so an
install that already holds one of these as disabled by the integration keeps it disabled.
Setup enables those entries once. An entry the user disabled is not the integration's to
touch, so only the ones the integration itself disabled qualify.
"""

from __future__ import annotations

from collections.abc import Iterable

# Disabled by default up to v0.11.0 (the first four) or v0.16.0 (charge_plan), enabled since.
NEWLY_ENABLED_SENSOR_KEYS: tuple[str, ...] = (
    "saving_vs_grid_today",
    "net_saving_today",
    "battery_discharge_kwh_today",
    "next_cheap_rate_start",
    "charge_plan",
)


def keys_to_enable(disabled_by_integration: Iterable[str]) -> list[str]:
    """The newly enabled sensor keys among the entities the integration itself disabled."""
    held = set(disabled_by_integration)
    return [key for key in NEWLY_ENABLED_SENSOR_KEYS if key in held]
