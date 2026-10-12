"""The accumulation store writes nothing until it has read what is saved."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    AccumulationStore,
)


class _Store:
    def __init__(self, data):
        self.data = data
        self.saves = []
        self.delayed = []

    async def async_load(self):
        return self.data

    async def async_save(self, payload):
        self.saves.append(payload)

    def async_delay_save(self, factory, delay):
        self.delayed.append(factory)


def _store(data=None) -> tuple[AccumulationStore, _Store]:
    store = AccumulationStore.__new__(AccumulationStore)
    fake = _Store(data)
    store._store = fake
    store._bill_start_day = 1
    store.state = AccumulationState()
    store._loaded = False
    return store, fake


def test_a_save_queued_before_the_load_is_dropped():
    store, fake = _store()
    store.schedule_save()
    assert fake.delayed == []


async def test_a_direct_save_before_the_load_is_dropped():
    store, fake = _store()
    await store.async_save()
    assert fake.saves == []


async def test_after_the_load_saves_go_through():
    store, fake = _store()
    await store.async_load()
    store.schedule_save()
    await store.async_save()
    assert len(fake.delayed) == 1 and len(fake.saves) == 1


async def test_a_fresh_install_with_nothing_saved_can_save_after_the_load():
    store, fake = _store(data=None)
    await store.async_load()
    store.schedule_save()
    assert len(fake.delayed) == 1


async def test_a_failed_load_still_opens_saving_so_the_install_is_not_stuck():
    store, fake = _store()

    async def boom():
        raise OSError("disk")

    fake.async_load = boom
    with pytest.raises(OSError):
        await store.async_load()
    store.schedule_save()
    assert len(fake.delayed) == 1


def test_a_store_built_without_the_flag_behaves_as_before():
    store = AccumulationStore.__new__(AccumulationStore)
    store._store = MagicMock()
    store.state = AccumulationState()
    store.schedule_save()
    store._store.async_delay_save.assert_called_once()
