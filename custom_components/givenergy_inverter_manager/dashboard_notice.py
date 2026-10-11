"""
dashboard_notice.py - tells the user once how to add the dashboard.

The dashboard is a Lovelace strategy that builds itself. Home Assistant gives an integration
no supported way to add a dashboard for the user, so the integration asks the user to add it
from Community dashboards, and says how in a persistent notification.

It does that once for each config entry. The answer is saved as the dashboard_url_path option:

  absent   setup has not looked yet. It looks, and writes one of the two values below.
  a path   a dashboard that uses the strategy exists, at this URL path. Nothing is shown.
  ""       none was found, and the notification was sent. A user who later deletes the
           dashboard, or never adds it, is not asked again.

Finding a dashboard reads the dashboards the Lovelace component holds in memory. That is not a
public interface, so every failure is read as "none found". The cost of being wrong is one
notification.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DASHBOARD_URL_PATH, DOMAIN
from .logging import get_logger
from .strategy import STRATEGY_TYPE

_LOG = get_logger(__name__)

NOTIFICATION_ID = f"{DOMAIN}_add_dashboard"
NOTIFICATION_TITLE = "Add the GivEnergy dashboard"
DOCS_URL = "https://github.com/macuistin/givenergy_inverter_manager/blob/main/docs/dashboard.md"
NOTIFICATION_MESSAGE = (
    "GivEnergy Inverter Manager builds its dashboard for you. Home Assistant needs you to add "
    "it once:\n\n"
    "1. Go to **Settings → Dashboards → Add dashboard**.\n"
    "2. Under **Community dashboards**, pick **GivEnergy**.\n"
    "3. Add it.\n\n"
    "It builds itself from your entities each time it opens, so it follows a new tariff or a "
    "new device. If GivEnergy is not listed, reload the browser tab and try again.\n\n"
    f"[More about the dashboard]({DOCS_URL})"
)
# The URL path Home Assistant gives the default dashboard.
_DEFAULT_URL_PATH = "lovelace"


def _dashboards(hass: HomeAssistant) -> dict[str | None, Any]:
    """The dashboards Lovelace holds, by URL path. The default dashboard has the key None.

    Lovelace keeps them in hass.data. Newer releases use an object with a dashboards attribute
    and older ones a dict, as for the resources (dashboard/hacs.py).
    """
    data = hass.data.get("lovelace")
    found = data.get("dashboards") if isinstance(data, dict) else getattr(data, "dashboards", None)
    return found if isinstance(found, dict) else {}


async def _uses_strategy(dashboard: Any) -> bool:
    """True when this dashboard's saved configuration names our strategy."""
    try:
        config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 - a dashboard with no saved config, or one that cannot load
        return False
    strategy = config.get("strategy") if isinstance(config, dict) else None
    return isinstance(strategy, dict) and strategy.get("type") == STRATEGY_TYPE


async def async_find_dashboard(hass: HomeAssistant) -> str | None:
    """The URL path of a dashboard that uses the strategy, or None when none is found."""
    try:
        dashboards = dict(_dashboards(hass))
        for url_path, dashboard in dashboards.items():
            if await _uses_strategy(dashboard):
                return url_path or _DEFAULT_URL_PATH
    except Exception:  # noqa: BLE001 - Lovelace internals changed. The user is told instead
        _LOG.debug("Could not look for the dashboard in Lovelace", exc_info=True)
    return None


def _remember(hass: HomeAssistant, entry: ConfigEntry, url_path: str) -> None:
    """Save the answer. Called before the update listener exists, so nothing reloads."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_DASHBOARD_URL_PATH: url_path}
    )


def _create_notification(hass: HomeAssistant) -> None:
    from homeassistant.components import persistent_notification  # noqa: PLC0415

    persistent_notification.async_create(
        hass, NOTIFICATION_MESSAGE, title=NOTIFICATION_TITLE, notification_id=NOTIFICATION_ID
    )


def _dismiss_notification(hass: HomeAssistant) -> None:
    from homeassistant.components import persistent_notification  # noqa: PLC0415

    persistent_notification.async_dismiss(hass, NOTIFICATION_ID)


async def async_announce_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Look for the dashboard once for this entry, and tell the user how to add it if none exists.

    Does nothing on a reload or a restart once an answer is saved, so a dashboard the user
    deleted stays deleted and the notification is not sent again. Does nothing, and saves
    nothing, while Lovelace is not loaded: with no dashboards there is nothing to add one to,
    and the next start asks again.
    """
    if CONF_DASHBOARD_URL_PATH in entry.options or hass.data.get("lovelace") is None:
        return
    if found := await async_find_dashboard(hass):
        _LOG.info("Found the GivEnergy dashboard at /%s", found)
        _remember(hass, entry, found)
        return
    _create_notification(hass)
    _remember(hass, entry, "")


def async_dismiss_announcement(hass: HomeAssistant) -> None:
    """Remove the notification, for when the integration is removed."""
    _dismiss_notification(hass)
