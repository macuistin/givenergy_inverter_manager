"""
shadow_search_store.py - collect every plan of the current tariff's country for the search.

It lists the suppliers, plans and areas through the store access, so each call runs off the event
loop, and parses each plan into a definition. A plan is included when it has no areas (the area
`all`) or holds the area of the current tariff. A plan with another area only, or one that cannot
be read, is counted and left out, never guessed. Nothing here writes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from .core.shadow_search import Candidate
from .lib.tariff import DefinitionError, TariffDefinition
from .lib.tariffstore import StoreError

_LOG = logging.getLogger(__name__)
ALL_AREAS = "all"
READ_ERRORS = (StoreError, DefinitionError, OSError, ValueError, KeyError, TypeError)


class StoreReader(Protocol):
    async def async_providers(self, country: str) -> dict[str, str]: ...

    async def async_tariffs(self, country: str, provider: str, on: date) -> dict[str, str]: ...

    async def async_areas(
        self, country: str, provider: str, tariff: str, on: date
    ) -> dict[str, str]: ...

    async def async_definition(  # noqa: PLR0913
        self, country: str, provider: str, tariff: str, on: date, area: str = "all",
        export: str | None = None,
    ) -> TariffDefinition: ...


@dataclass
class Gathered:
    """The plans found, how many were left out, and where each came from."""

    on: date
    wanted: str | None  # the area of the current tariff
    candidates: list[Candidate] = field(default_factory=list)
    places: dict[str, dict[str, str]] = field(default_factory=dict)  # key -> store location
    other_area: int = 0
    unreadable: int = 0


def plan_key(provider: str, tariff: str, area: str) -> str:
    return f"{provider}/{tariff}/{area}"


def _same_plan(source: Mapping[str, Any] | None, provider: str, tariff: str) -> bool:
    return bool(source) and (source or {}).get("provider") == provider and (
        (source or {}).get("tariff") == tariff
    )


def _area_for(areas: Mapping[str, str], wanted: str | None) -> str | None:
    if wanted and wanted in areas:
        return wanted
    return ALL_AREAS if ALL_AREAS in areas else None


async def gather(
    store: StoreReader, country: str, on: date, source: Mapping[str, Any] | None
) -> Gathered:
    """Every plan in force on *on* in *country* that fits the area of *source*."""
    wanted = (source or {}).get("area")
    found = Gathered(on, wanted)
    for provider in await store.async_providers(country):
        for tariff in await store.async_tariffs(country, provider, on):
            if _same_plan(source, provider, tariff):
                continue  # the current plan is priced from the saved options instead
            await _add_plan(store, found, (country, provider, tariff))
    return found


async def _add_plan(store: StoreReader, found: Gathered, plan: tuple[str, str, str]) -> None:
    country, provider, tariff = plan
    try:
        area = _area_for(await store.async_areas(country, provider, tariff, found.on), found.wanted)
        if area is None:
            found.other_area += 1
            return
        definition = await store.async_definition(country, provider, tariff, found.on, area=area)
    except READ_ERRORS as err:
        _LOG.debug("Left out %s/%s: %s", provider, tariff, err)
        found.unreadable += 1
        return
    key = plan_key(provider, tariff, area)
    label = f"{definition.provider.name} {definition.name}"
    found.candidates.append(Candidate(key, label, definition))
    found.places[key] = {
        "country": country, "provider": provider, "tariff": tariff, "area": area,
    }
