"""Collecting a country's plans for the search: the area rule and what is left out."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.givenergy_inverter_manager.lib.tariffstore import StoreError
from custom_components.givenergy_inverter_manager.shadow_search_store import gather
from tests.core.shadow_helpers import _definition

ON = date(2026, 11, 13)


class FakeStore:
    """Two suppliers: one plan for everyone, one with two areas, one that cannot be read."""

    AREAS = {
        ("a", "flat"): {"all": "Everywhere"},
        ("a", "regional"): {"urban": "Urban", "rural": "Rural"},
        ("b", "other"): {"north": "North"},
        ("b", "broken"): {"all": "Everywhere"},
        ("b", "mine"): {"all": "Everywhere"},
    }

    async def async_providers(self, country: str) -> dict[str, str]:
        return {"a": "A", "b": "B"}

    async def async_tariffs(self, country: str, provider: str, on: date) -> dict[str, str]:
        return {t: t for (p, t) in self.AREAS if p == provider}

    async def async_areas(self, country: str, provider: str, tariff: str, on: date):  # type: ignore[no-untyped-def]
        return self.AREAS[(provider, tariff)]

    async def async_definition(self, country, provider, tariff, on, area="all", export=None):  # type: ignore[no-untyped-def]
        if tariff == "broken":
            raise StoreError("checksum")
        return _definition()


@pytest.mark.asyncio
async def test_plans_for_my_area_and_plans_with_no_area_are_included() -> None:
    found = await gather(FakeStore(), "IE", ON, {"provider": "b", "tariff": "mine", "area": "rural"})
    assert sorted(found.places) == ["a/flat/all", "a/regional/rural"]
    assert found.other_area == 1  # the plan that only has the north
    assert found.unreadable == 1  # the plan that failed its check
    assert all(c.key in found.places for c in found.candidates)


@pytest.mark.asyncio
async def test_the_current_plan_is_not_listed_again() -> None:
    found = await gather(FakeStore(), "IE", ON, {"provider": "a", "tariff": "flat", "area": "all"})
    assert "a/flat/all" not in found.places


@pytest.mark.asyncio
async def test_without_a_source_only_plans_with_no_area_are_included() -> None:
    found = await gather(FakeStore(), "IE", ON, None)
    assert sorted(found.places) == ["a/flat/all", "b/mine/all"]
    assert found.other_area == 2
