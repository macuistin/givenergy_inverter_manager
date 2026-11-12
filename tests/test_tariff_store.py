"""The tariff store as the screens use it: awaitable, cached, and fetched without blocking."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariffstore import (
    FolderCache,
    Store,
    StoreError,
    folder_reader,
)
from custom_components.givenergy_inverter_manager.tariff_store import (
    TariffStoreAccess,
    session_reader,
)
from tests.lib.tariffstore.building import build_store
from tests.lib.tariffstore.fixtures import write_store

DAY = date(2026, 11, 12)


class FakeHass:
    """Runs executor jobs inline, as far as the access class can tell."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = loop
        self.config = SimpleNamespace(path=lambda *parts: str(Path("/nonexistent", *parts)))

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


@pytest.fixture
def tariffs(tmp_path: Path) -> Path:
    folder = write_store(tmp_path)
    build_store(folder)
    return folder


def _access(tariffs: Path, cache: Path) -> TariffStoreAccess:
    store = Store(folder_reader(tariffs), FolderCache(cache))
    return TariffStoreAccess(FakeHass(), store)  # type: ignore[arg-type]


async def test_lists_countries_providers_tariffs_and_areas(tariffs: Path, tmp_path: Path) -> None:
    access = _access(tariffs, tmp_path / "cache")
    assert "IE" in await access.async_countries()
    providers = await access.async_providers("IE")
    assert list(providers) == ["p"]
    tariff_ids = await access.async_tariffs("IE", "p", DAY)
    assert list(tariff_ids) == ["plan"]
    assert list(await access.async_areas("IE", "p", "plan", DAY)) == ["rural", "urban"]


async def test_the_definition_is_parsed_and_priced_from_the_store(
    tariffs: Path, tmp_path: Path
) -> None:
    definition = await _access(tariffs, tmp_path / "cache").async_definition("IE", "p", "plan", DAY, "urban")
    assert definition.country == "IE"
    assert definition.currency == "EUR"


async def test_a_tariff_already_read_is_still_readable_with_no_network(
    tariffs: Path, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    await _access(tariffs, cache).async_definition("IE", "p", "plan", DAY, "urban")

    def unreachable(path: str) -> bytes:
        raise OSError("no network")

    offline = TariffStoreAccess(
        FakeHass(),  # type: ignore[arg-type]
        Store(unreachable, FolderCache(cache), max_age=0),
    )
    definition = await offline.async_definition("IE", "p", "plan", DAY, "urban")
    assert definition.country == "IE"
    assert offline.offline


async def test_a_store_never_read_and_unreachable_is_an_error(tmp_path: Path) -> None:
    def unreachable(path: str) -> bytes:
        raise OSError("no network")

    access = TariffStoreAccess(
        FakeHass(),  # type: ignore[arg-type]
        Store(unreachable, FolderCache(tmp_path / "cache")),
    )
    with pytest.raises(StoreError):
        await access.async_countries()


def test_the_reader_refuses_a_store_that_is_not_https() -> None:
    with pytest.raises(ValueError, match="https"):
        session_reader(FakeHass(), "http://example.invalid/tariffs")  # type: ignore[arg-type]


async def test_the_reader_fetches_on_the_event_loop_from_a_worker_thread() -> None:
    seen: list[str] = []

    class Reply:
        def raise_for_status(self) -> None:
            return None

        async def read(self) -> bytes:
            return b"{}"

        async def __aenter__(self) -> Reply:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    class Session:
        def get(self, url: str, timeout: Any) -> Reply:
            seen.append(url)
            return Reply()

    hass = FakeHass(asyncio.get_running_loop())
    read = session_reader(
        hass,  # type: ignore[arg-type]
        "https://example.invalid/tariffs/",
        lambda _hass: Session(),
    )
    assert await asyncio.to_thread(read, "index.json") == b"{}"
    assert seen == ["https://example.invalid/tariffs/index.json"]


async def test_the_default_access_reads_from_the_store_over_https(tmp_path: Path) -> None:
    hass = FakeHass()
    hass.config = SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts)))
    access = TariffStoreAccess(hass)  # type: ignore[arg-type]
    assert access.offline is False


async def test_a_refresh_reads_the_countries_index_again(tariffs: Path, tmp_path: Path) -> None:
    access = _access(tariffs, tmp_path / "cache")
    await access.async_countries()
    await access.async_refresh()
    assert "IE" in await access.async_countries()


async def test_a_network_error_becomes_an_os_error_for_the_client() -> None:
    from aiohttp import ClientConnectionError

    class Session:
        def get(self, url: str, timeout: Any) -> Any:
            raise ClientConnectionError("down")

    hass = FakeHass(asyncio.get_running_loop())
    read = session_reader(hass, "https://example.invalid/t", lambda _hass: Session())  # type: ignore[arg-type]
    with pytest.raises(OSError, match="down"):
        await asyncio.to_thread(read, "index.json")


def test_the_default_session_is_homes_assistants_shared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import ModuleType

    module = ModuleType("homeassistant.helpers.aiohttp_client")
    module.async_get_clientsession = lambda hass: ("session", hass)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.aiohttp_client", module)
    from custom_components.givenergy_inverter_manager.tariff_store import _home_assistant_session

    assert _home_assistant_session("hass") == ("session", "hass")  # type: ignore[arg-type]
