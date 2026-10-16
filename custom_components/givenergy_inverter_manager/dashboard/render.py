"""
render.py - builds the dashboard dict and reads what Home Assistant says about the host.

_generate is the one place a dashboard is built. The Lovelace strategy calls it each time a
dashboard opens, through build_dashboard.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .hacs import async_lovelace_resource_urls
from .registry import HostFacts, async_admin_user_ids
from .views import TAB_VIEWS, Builder

# The first release whose history and statistics graphs draw a series in its own colour.
_SERIES_COLOURS_FROM = (2026, 6)


def build_dashboard(
    hass: HomeAssistant,
    entry: ConfigEntry,
    facts: HostFacts,
    registry=None,
) -> dict:
    """Return the dashboard as a dict, for the Lovelace strategy.

    *facts* is what Home Assistant says about the Lovelace resources and whether the viewer is
    an administrator. *registry* answers the two entity registry calls the builder makes. It
    defaults to the registry of *hass*.
    """
    return _generate(hass, entry, facts, registry)


async def async_host_facts(hass: HomeAssistant, *, is_admin: bool) -> HostFacts:
    """Read the Lovelace resources, and the administrators when the viewer is one.

    A viewer who is not an administrator gets no administrator list, because the dashboard
    built for them has no Settings view to put it in. A role change shows when the page of a
    strategy dashboard is reloaded.
    """
    admin_ids = await async_admin_user_ids(hass) if is_admin else ()
    resources = await async_lovelace_resource_urls(hass)
    return HostFacts(resources, admin_ids, is_admin, series_colours=_draws_series_colours())


def _draws_series_colours() -> bool:
    """True on a Home Assistant release whose charts take a colour for each series (2026.6)."""
    from homeassistant import const  # noqa: PLC0415

    version = (getattr(const, "MAJOR_VERSION", 0), getattr(const, "MINOR_VERSION", 0))
    return version >= _SERIES_COLOURS_FROM


def _generate(
    hass: HomeAssistant,
    entry: ConfigEntry,
    facts: HostFacts,
    registry=None,
) -> dict:
    """Build the Lovelace configuration as a dict.

    Uses actual entity IDs from the entity registry so names customised in the HA
    UI are respected. A tile or card appears only when its entity is registered and
    enabled, and the feature behind it (inverter temperature, solar forecast) is
    configured. The cards of an optional device (EV charger, immersion switch or
    sensor) are always built, and a visibility condition shows them while it exists.
    """
    builder = Builder(hass, entry, facts, registry)
    subviews = builder.build_subviews()
    tabs = [spec.build(builder) for spec in TAB_VIEWS]
    return {"views": [view for view in tabs + subviews if view["sections"]]}
