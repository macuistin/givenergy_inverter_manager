"""
strategy.py - serves the dashboard as a Lovelace strategy.

With this, a dashboard's whole configuration can be:

    strategy:
      type: custom:givenergy-manager

The frontend loads a small JavaScript file from this integration. The file calls
a websocket command that returns the same dashboard the get_dashboard_yaml
service writes, built from the current registry and options each time the
dashboard opens.

Nothing here is required by the rest of the integration. The service and the
generated file work without it.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION
from .dashboard import async_host_facts, build_dashboard
from .logging import get_logger
from .services import loaded_entries

_LOG = get_logger(__name__)

WS_TYPE = f"{DOMAIN}/dashboard"
STRATEGY_URL_PATH = f"/{DOMAIN}/givenergy-manager-strategy.js"
STRATEGY_FILE = Path(__file__).parent / "frontend" / "givenergy-manager-strategy.js"
_REGISTERED_KEY = f"{DOMAIN}_strategy_registered"
_EXTRA_MODULE_URL_KEY = "frontend_extra_module_url"


async def async_dashboard_for_websocket(hass: HomeAssistant) -> dict | None:
    """Return the dashboard dict for the first loaded config entry, or None if none is loaded.

    This is the entry the get_dashboard_yaml action uses too.
    """
    entries = loaded_entries(hass)
    if not entries:
        return None
    facts = await async_host_facts(hass)
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
        config = await async_dashboard_for_websocket(hass)
        if config is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "GivEnergy Inverter Manager is not set up"
            )
            return
        connection.send_result(msg["id"], config)

    websocket_api.async_register_command(hass, ws_dashboard)


async def _serve_strategy_file(hass: HomeAssistant) -> None:
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    if getattr(hass, "http", None) is None:
        _LOG.debug("No HTTP server, so the dashboard strategy file is not served")
        return
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STRATEGY_URL_PATH, str(STRATEGY_FILE), cache_headers=False)]
        )
    except RuntimeError as err:
        _LOG.warning("Could not serve the dashboard strategy file: %s", err)
        return
    if _EXTRA_MODULE_URL_KEY not in hass.data:
        _LOG.debug("The frontend is not loaded, so the strategy file is not added to it")
        return
    from homeassistant.components import frontend  # noqa: PLC0415

    frontend.add_extra_js_url(hass, f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}")
