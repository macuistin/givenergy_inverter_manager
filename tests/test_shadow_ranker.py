"""The ranker: it prices the store's plans over the last bill, keeps the result, and fails soft."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager import shadow_ranker
from custom_components.givenergy_inverter_manager.lib.tariff import SlotHistory
from custom_components.givenergy_inverter_manager.lib.tariffstore import StoreError
from tests.core.test_shadow_search import _definition
from tests.core.test_shadow_tariffs import ACTIVE
from tests.lib.tariff.test_reprice import _october_bill_days
from tests.test_shadow_search_store import FakeStore

TODAY = date(2026, 11, 16)  # the last whole bill is 16 Sep to 15 Oct


class Store(FakeStore):
    broken = False

    def __init__(self, hass: Any) -> None:
        pass

    async def async_refresh(self) -> None:
        if Store.broken:
            raise StoreError("offline")

    async def async_definition(self, country, provider, tariff, on, area="all", export=None):  # type: ignore[no-untyped-def]
        if tariff == "broken":
            raise StoreError("checksum")
        return _definition(base_rate=0.01 if tariff == "flat" else 0.9)


class Hass:
    config = SimpleNamespace(country="IE")

    async def async_add_executor_job(self, fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)


def _history() -> SlotHistory:
    history = SlotHistory(ZoneInfo("Europe/Dublin"))
    history._days = {day.day: day for day in _october_bill_days()}
    return history


def _ranker(history: SlotHistory | None, options: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    entry = SimpleNamespace(data={}, options=options if options is not None else ACTIVE)
    return shadow_ranker.ShadowRanker(Hass(), entry, lambda: history)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _store(monkeypatch: pytest.MonkeyPatch) -> None:
    Store.broken = False
    monkeypatch.setattr(shadow_ranker, "TariffStoreAccess", Store)


@pytest.mark.asyncio
async def test_every_plan_is_ranked_against_the_saved_tariff() -> None:
    ranker = _ranker(_history())
    ranking = await ranker.async_refresh(TODAY, "Europe/Dublin")
    assert ranking is ranker.ranking and ranking is not None
    assert ranking.compared == 3  # yours and the two plans that fit every area
    assert ranking.current_rank > 1 and ranking.saving > 0
    assert ranking.left_out == 3  # two for other areas, one that failed its check
    assert ranking.days_recorded == ranking.days == 30


@pytest.mark.asyncio
async def test_no_history_means_no_ranking() -> None:
    ranker = _ranker(None)
    assert await ranker.async_refresh(TODAY, "Europe/Dublin") is None
    assert ranker.ranking is None


@pytest.mark.asyncio
async def test_an_unreadable_store_keeps_the_last_ranking() -> None:
    ranker = _ranker(_history())
    first = await ranker.async_refresh(TODAY, "Europe/Dublin")
    Store.broken = True
    assert await ranker.async_refresh(TODAY, "Europe/Dublin") is None
    assert ranker.ranking is first


@pytest.mark.asyncio
async def test_a_country_comes_from_the_tariff_followed_from_the_store() -> None:
    options = {**ACTIVE, "tariff_source": {"country": "GB", "provider": "z", "tariff": "t",
                                              "area": "all"}}
    ranker = _ranker(_history(), options)
    assert await ranker.async_refresh(TODAY, "Europe/Dublin") is not None


@pytest.mark.asyncio
async def test_no_country_means_no_ranking() -> None:
    ranker = _ranker(_history())
    ranker._hass.config = SimpleNamespace(country=None)  # type: ignore[attr-defined]
    assert await ranker.async_refresh(TODAY, "Europe/Dublin") is None
