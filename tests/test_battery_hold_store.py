"""The saved record of a battery hold: read back whole, cleared, and never fatal."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from custom_components.givenergy_inverter_manager import battery_hold_store
from custom_components.givenergy_inverter_manager.core.ev_battery_hold import HoldRecord
from custom_components.givenergy_inverter_manager.lib.givtcp.model import (
    BatteryPause,
    PauseSetting,
)

RECORD = HoldRecord(
    PauseSetting(BatteryPause.DISCHARGE, (time(23, 0), time(8, 0))),
    datetime(2031, 3, 4, 10, 45, tzinfo=timezone.utc),
)


class _Store:
    def __init__(self, data=None, fail=False):
        self.data = data
        self.fail = fail

    async def async_load(self):
        if self.fail:
            raise OSError("unreadable")
        return self.data

    async def async_save(self, data):
        if self.fail:
            raise OSError("read-only")
        self.data = data


def _store(monkeypatch, fake: _Store) -> battery_hold_store.BatteryHoldStore:
    monkeypatch.setattr(battery_hold_store, "_create_store", lambda hass: fake)
    return battery_hold_store.BatteryHoldStore(object())


async def test_a_saved_record_is_read_back_whole(monkeypatch):
    fake = _Store()
    store = _store(monkeypatch, fake)

    await store.async_save(RECORD)

    assert await store.async_load() == RECORD


async def test_saving_none_clears_the_record(monkeypatch):
    fake = _Store(RECORD.as_dict())
    store = _store(monkeypatch, fake)

    await store.async_save(None)

    assert await store.async_load() is None


@pytest.mark.parametrize("data", [None, {}, {"pause": "Nonsense"}])
async def test_nothing_or_an_unreadable_record_loads_as_none(monkeypatch, data):
    assert await _store(monkeypatch, _Store(data)).async_load() is None


async def test_a_store_that_fails_does_not_stop_setup_or_a_hold(monkeypatch):
    store = _store(monkeypatch, _Store(fail=True))

    assert await store.async_load() is None
    await store.async_save(RECORD)
