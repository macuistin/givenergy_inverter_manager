"""
strategy.py - serves the dashboard as a Lovelace strategy.

The dashboard is a strategy. Its whole configuration is:

    strategy:
      type: custom:givenergy-manager

The frontend loads a small JavaScript file from this integration. The file calls a websocket
command that builds the dashboard from the current registry and options each time the
dashboard opens, and lists the strategy under Community dashboards when a dashboard is added.

The command reads the connection's user to decide whether the Settings view is built. Nothing
else in the integration needs the strategy.

Home Assistant gives the browser one chance, 5 seconds, to find the strategy's element, and does
not try again. The script copes on its side: it asks again while the command is not ready yet,
and rebuilds the dashboard if it finds the timeout message on the page when it loads.
"""

from __future__ import annotations

import time
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION
from .dashboard import async_host_facts, build_dashboard
from .logging import get_logger
from .services import loaded_entries

_LOG = get_logger(__name__)

WS_TYPE = f"{DOMAIN}/dashboard"
# The strategy type a dashboard names in its configuration.
STRATEGY_TYPE = "custom:givenergy-manager"
STRATEGY_URL_PATH = f"/{DOMAIN}/givenergy-manager-strategy.js"
STRATEGY_FILE = Path(__file__).parent / "frontend" / "givenergy-manager-strategy.js"
_REGISTERED_KEY = f"{DOMAIN}_strategy_registered"
_BOOT_KEY = f"{DOMAIN}_strategy_boot"
_EXTRA_MODULE_URL_KEY = "frontend_extra_module_url"


async def async_dashboard_for_websocket(hass: HomeAssistant, *, is_admin: bool) -> dict | None:
    """Return the dashboard dict for the first loaded config entry, or None if none is loaded.

    *is_admin* is whether the connection's user is an administrator. Only then does the
    dashboard hold the Settings view.
    """
    entries = loaded_entries(hass)
    if not entries:
        return None
    facts = await async_host_facts(hass, is_admin=is_admin)
    return build_dashboard(hass, entries[0], facts)


async def async_register_strategy(hass: HomeAssistant) -> None:
    """Register the websocket command and serve the strategy JavaScript.

    Safe to call on every entry setup: it registers once per Home Assistant run.
    """
    if hass.data.get(_REGISTERED_KEY):
        return
    hass.data[_REGISTERED_KEY] = True
    _register_websocket_command(hass)
    await _serve_strategy_file(hass)


def _register_websocket_command(hass: HomeAssistant) -> None:
    import voluptuous as vol  # noqa: PLC0415
    from homeassistant.components import websocket_api  # noqa: PLC0415

    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE})
    @websocket_api.async_response
    async def ws_dashboard(hass, connection, msg):
        # The authenticated user decides who sees Settings. The schema accepts no other field,
        # so there is nothing in the message a client could use to ask for it.
        config = await async_dashboard_for_websocket(hass, is_admin=connection.user.is_admin)
        if config is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "GivEnergy Inverter Manager is not set up"
            )
            return
        connection.send_result(msg["id"], config)

    websocket_api.async_register_command(hass, ws_dashboard)


def strategy_module_url(hass: HomeAssistant) -> str:
    """The address the page imports the script from, which is new for each Home Assistant start.

    The version tells releases apart. The start time tells starts apart, so a wrong response a
    browser kept from one start's first seconds is never asked for again after the next start.
    """
    if _BOOT_KEY not in hass.data:
        hass.data[_BOOT_KEY] = str(int(time.time()))
    boot = hass.data[_BOOT_KEY]
    return f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}&boot={boot}"


def _strategy_file_view():
    """The view that serves the script. It is built here so this module imports without one."""
    from aiohttp import web  # noqa: PLC0415
    from homeassistant.components.http import HomeAssistantView  # noqa: PLC0415

    class StrategyFileView(HomeAssistantView):
        """The dashboard script. The browser asks the server whether its copy is current."""

        url = STRATEGY_URL_PATH
        name = f"{DOMAIN}:strategy_file"
        requires_auth = False

        async def get(self, request: web.Request) -> web.StreamResponse:
            # no-cache means keep a copy but check it first. The ETag makes the check a small
            # 304 while the file is unchanged, and a copy that is wrong mends itself on the next
            # load. A long lifetime would keep a wrong copy for weeks.
            return web.FileResponse(STRATEGY_FILE, headers={"Cache-Control": "no-cache"})

    return StrategyFileView()


async def _serve_strategy_file(hass: HomeAssistant) -> None:
    if getattr(hass, "http", None) is None:
        _LOG.debug("No HTTP server, so the dashboard strategy file is not served")
        return
    try:
        hass.http.register_view(_strategy_file_view())
    except RuntimeError as err:
        _LOG.warning("Could not serve the dashboard strategy file: %s", err)
        return
    if _EXTRA_MODULE_URL_KEY not in hass.data:
        _LOG.debug("The frontend is not loaded, so the strategy file is not added to it")
        return
    from homeassistant.components import frontend  # noqa: PLC0415

    frontend.add_extra_js_url(hass, strategy_module_url(hass))
