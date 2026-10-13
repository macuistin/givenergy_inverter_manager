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
not try again. A page that loaded the script late shows "Timeout waiting for strategy element"
until it is reloaded. Once setup is done the integration tells the dashboards that use it to
build again (`async_nudge_dashboards`), so a page that has the script by then recovers by itself.
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
# The strategy type a dashboard names in its configuration.
STRATEGY_TYPE = "custom:givenergy-manager"
STRATEGY_URL_PATH = f"/{DOMAIN}/givenergy-manager-strategy.js"
STRATEGY_FILE = Path(__file__).parent / "frontend" / "givenergy-manager-strategy.js"
_REGISTERED_KEY = f"{DOMAIN}_strategy_registered"
_NUDGED_KEY = f"{DOMAIN}_dashboards_nudged"
EVENT_LOVELACE_UPDATED = "lovelace_updated"
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


async def _serve_strategy_file(hass: HomeAssistant) -> None:
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    if getattr(hass, "http", None) is None:
        _LOG.debug("No HTTP server, so the dashboard strategy file is not served")
        return
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STRATEGY_URL_PATH, str(STRATEGY_FILE), cache_headers=True)]
        )
    except RuntimeError as err:
        _LOG.warning("Could not serve the dashboard strategy file: %s", err)
        return
    if _EXTRA_MODULE_URL_KEY not in hass.data:
        _LOG.debug("The frontend is not loaded, so the strategy file is not added to it")
        return
    from homeassistant.components import frontend  # noqa: PLC0415

    frontend.add_extra_js_url(hass, f"{STRATEGY_URL_PATH}?v={INTEGRATION_VERSION}")


async def async_nudge_dashboards(hass: HomeAssistant) -> int:
    """Tell open dashboards that use this strategy to build again, once per Home Assistant run.

    Home Assistant sends `lovelace_updated` when a dashboard is saved, and an open dashboard
    fetches its configuration again, which builds the strategy again. A page that had not yet
    loaded the strategy script when it first asked will have it now. Only storage dashboards
    whose configuration names this strategy get the event, and every failure to read a
    dashboard is skipped, because this is a courtesy and never part of setup. Returns how many
    dashboards were told.
    """
    if hass.data.get(_NUDGED_KEY):
        return 0
    hass.data[_NUDGED_KEY] = True
    nudged = 0
    for url_path in await _dashboards_using_the_strategy(hass):
        hass.bus.async_fire(EVENT_LOVELACE_UPDATED, {"url_path": url_path})
        nudged += 1
    return nudged


async def _dashboards_using_the_strategy(hass: HomeAssistant) -> list[str | None]:
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

        dashboards = dict(hass.data[LOVELACE_DATA].dashboards)
    except Exception:  # noqa: BLE001 - another integration's internals, so any failure means none
        _LOG.debug("The dashboards could not be listed, so none is told to build again")
        return []
    found: list[str | None] = []
    for url_path, dashboard in dashboards.items():
        if getattr(dashboard, "mode", None) != "storage":
            continue
        try:
            config = await dashboard.async_load(False)
        except Exception:  # noqa: BLE001 - a dashboard with no saved configuration, or one that cannot be read
            continue
        strategy = config.get("strategy") if isinstance(config, dict) else None
        if isinstance(strategy, dict) and strategy.get("type") == STRATEGY_TYPE:
            found.append(url_path)
    return found
