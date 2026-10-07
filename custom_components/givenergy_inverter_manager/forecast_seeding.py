"""Seed the forecast accuracy history from the Home Assistant recorder.

A new install has no forecast and solar pairs, so the accuracy correction waits for five
nights. The recorder usually holds the forecast sensor and the daily solar counter for the
last ten days, so the first load rebuilds those nights (see core/forecast_seeding.py).

Best effort. Anything that goes wrong is logged at debug level and setup carries on.
"""

from __future__ import annotations

import math
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from .core.forecast_seeding import (
    Reading,
    RecordedReadings,
    query_start,
    seed_forecast_records,
)
from .logging import get_logger

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .accumulation import AccumulationStore

_LOG = get_logger(__name__)


def _reading(state: Any) -> Reading | None:
    """A recorded state as a numeric reading, None for unknown, unavailable or text."""
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return Reading(at=state.last_updated, value=value)


def _readings(states: list[Any]) -> list[Reading]:
    return [r for r in map(_reading, states) if r is not None]


def _recorded_states(
    hass: HomeAssistant, entity_ids: list[str], start: datetime, end: datetime
) -> dict[str, list[Any]]:
    """Query the recorder database. Blocking, so it runs in the recorder's executor."""
    from homeassistant.components.recorder.history import get_significant_states

    return get_significant_states(
        hass,
        start,
        end,
        entity_ids,
        include_start_time_state=True,
        significant_changes_only=False,
        no_attributes=True,
    )


async def async_recorded_readings(
    hass: HomeAssistant, entity_ids: list[str], start: datetime, end: datetime
) -> dict[str, list[Reading]]:
    """The numeric states the recorder holds for the entities, empty without a recorder."""
    if "recorder" not in hass.config.components:
        return {}
    from homeassistant.helpers.recorder import get_instance

    instance = get_instance(hass)
    if not await instance.async_db_ready:
        return {}
    states = await instance.async_add_executor_job(
        partial(_recorded_states, hass, entity_ids, start, end)
    )
    return {entity_id: _readings(found) for entity_id, found in states.items()}


async def async_seed_forecast_accuracy(
    hass: HomeAssistant,
    acc: AccumulationStore,
    sources: tuple[str | None, str | None],
    now: datetime,
) -> int:
    """Fill an empty forecast history from the recorder, returning how many days it added.

    sources is the tomorrow forecast sensor and the daily solar counter, now the local time.
    Returns 0 and changes nothing when the history already holds a day, a source is missing
    or the recorder has no pair of values for any day.
    """
    forecast_entity, solar_entity = sources
    if not (acc.forecast_history_is_empty and forecast_entity and solar_entity):
        return 0
    tz = now.tzinfo
    if tz is None:
        return 0
    try:
        recorded = await async_recorded_readings(
            hass,
            [forecast_entity, solar_entity],
            query_start(now.date(), acc.forecast_history_days, tz),
            now,
        )
        records = seed_forecast_records(
            RecordedReadings(
                forecasts=recorded.get(forecast_entity, []),
                solar_totals=recorded.get(solar_entity, []),
            ),
            now.date(),
            tz,
            acc.forecast_history_days,
        )
    except Exception as err:  # best effort: setup must never depend on the recorder
        _LOG.debug("Could not seed the forecast accuracy from the recorder: %s", err)
        return 0
    return _store(acc, records)


def _store(acc: AccumulationStore, records: list[dict[str, Any]]) -> int:
    """Hand the rebuilt days to the store, unless a night was recorded while we waited."""
    if not records or not acc.forecast_history_is_empty:
        return 0
    acc.seed_forecast_history(records)
    _LOG.debug("Seeded the forecast accuracy with %d days from the recorder", len(records))
    return len(records)
