"""
tariff_store.py - reads the open tariff store for the setup and options screens.

The store client (`lib/tariffstore`) is plain blocking Python. This wraps it for Home Assistant:

- Every call runs in an executor job, never on the event loop.
- Files are fetched through Home Assistant's shared web session, so the host's proxy and
  certificate settings apply. The client's reader is a plain function, so it hands each request
  to the event loop and waits in the executor thread.
- What was read is kept in a folder under `.storage`, so a tariff in use is downloaded once and can
  be read again with no network.

Only static file paths are requested. Nothing about the install, its place or its usage is sent.
Home Assistant imports are lazy, as in `slot_store.py`, so the unit tests do not need them.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from .const import DEFAULT_TARIFF_STORE_URL, DOMAIN
from .lib.tariff import TariffDefinition, parse_definition
from .lib.tariffstore import FolderCache, Store, StoreError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")
REQUEST_TIMEOUT_S = 30
CACHE_FOLDER = f"{DOMAIN}_tariff_store"


def _home_assistant_session(hass: HomeAssistant) -> Any:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return async_get_clientsession(hass)


def session_reader(
    hass: HomeAssistant,
    base: str,
    get_session: Callable[[HomeAssistant], Any] = _home_assistant_session,
) -> Callable[[str], bytes]:
    """A `read(path)` for the store client that fetches through Home Assistant's web session.

    It blocks, so it is only called from an executor thread. A network failure raises OSError,
    which the client turns into a StoreError and answers from its cache.
    """
    if not base.startswith("https://"):
        raise ValueError("the tariff store is read over https only")

    async def fetch(url: str) -> bytes:
        from aiohttp import ClientError, ClientTimeout

        timeout = ClientTimeout(total=REQUEST_TIMEOUT_S)
        try:
            async with get_session(hass).get(url, timeout=timeout) as reply:
                reply.raise_for_status()
                body: bytes = await reply.read()
                return body
        except ClientError as err:
            raise OSError(str(err)) from err

    def read(path: str) -> bytes:
        future = asyncio.run_coroutine_threadsafe(fetch(f"{base.rstrip('/')}/{path}"), hass.loop)
        return future.result(REQUEST_TIMEOUT_S + 5)

    return read


_LOCKS: weakref.WeakKeyDictionary[Any, asyncio.Lock] = weakref.WeakKeyDictionary()


def _lock_of(hass: Any) -> asyncio.Lock:
    if hass not in _LOCKS:
        _LOCKS[hass] = asyncio.Lock()
    return _LOCKS[hass]


class TariffStoreAccess:
    """The store as the screens use it: awaitable calls that never block the event loop."""

    def __init__(self, hass: HomeAssistant, store: Store | None = None) -> None:
        self._hass = hass
        self._store = store if store is not None else Store(
            session_reader(hass, DEFAULT_TARIFF_STORE_URL),
            FolderCache(Path(hass.config.path(".storage", CACHE_FOLDER))),
        )

    @property
    def offline(self) -> bool:
        """True when the last read was answered from the cache because the store was unreachable."""
        return self._store.offline

    async def _run(self, call: Callable[[], _T]) -> _T:
        # One read at a time per install. The daily update check and the plan ranking both read
        # the store, and the client and its cache folder are not safe to use from two threads.
        async with _lock_of(self._hass):
            return await self._hass.async_add_executor_job(call)

    async def async_refresh(self) -> None:
        """Read the countries index again on the next call, whatever its age."""
        self._store.refresh()

    async def async_countries(self) -> dict[str, dict[str, Any]]:
        return await self._run(self._store.countries)

    async def async_providers(self, country: str) -> dict[str, str]:
        return await self._run(partial(self._store.providers, country))

    async def async_tariffs(self, country: str, provider: str, on: date) -> dict[str, str]:
        return await self._run(partial(self._store.tariffs, country, provider, on=on))

    async def async_areas(
        self, country: str, provider: str, tariff: str, on: date
    ) -> dict[str, str]:
        return await self._run(partial(self._store.areas, country, provider, tariff, on))

    async def async_definition(  # noqa: PLR0913
        self,
        country: str,
        provider: str,
        tariff: str,
        on: date,
        area: str = "all",
        export: str | None = None,
    ) -> TariffDefinition:
        """The checked, parsed definition of one area of a tariff on a day."""
        document = await self._run(
            partial(self._store.definition, country, provider, tariff, on,
                    area=area, export=export)
        )
        return parse_definition(document)


__all__ = ["StoreError", "TariffStoreAccess", "session_reader"]
