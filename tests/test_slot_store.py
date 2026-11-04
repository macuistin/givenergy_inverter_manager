"""The slot store writes nothing until it has read what is saved, and saves once a half hour."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from custom_components.givenergy_inverter_manager.lib.tariff.slot_history import SlotHistory
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay, SlotEnergy
from custom_components.givenergy_inverter_manager.slot_store import SlotStore

UTC = timezone.utc
NOON = datetime(2026, 6, 1, 12, 0, 5, tzinfo=UTC)


class _Store:
    def __init__(self, data=None, fail=False):
        self.data = data
        self.fail = fail
        self.saves = []
        self.delayed = []

    async def async_load(self):
        if self.fail:
            raise ValueError("unreadable")
        return self.data

    async def async_save(self, payload):
        self.saves.append(payload)

    def async_delay_save(self, factory, delay):
        self.delayed.append(factory)


def _store(data=None, fail=False) -> tuple[SlotStore, _Store]:
    # The unit tests stub Home Assistant's Store, so build around __init__. The end-to-end suite
    # builds it for real.
    store = SlotStore.__new__(SlotStore)
    fake = _Store(data, fail)
    store._store = fake
    store._tz = UTC
    store.history = SlotHistory(UTC)
    store._loaded = False
    store._saved_slot = None
    return store, fake


def _energy() -> SlotEnergy:
    return SlotEnergy(flows={"import": 0.1})


def test_a_save_queued_before_the_load_is_dropped():
    store, fake = _store()
    store.schedule_save()
    assert fake.delayed == []


async def test_a_direct_save_before_the_load_is_dropped():
    store, fake = _store()
    await store.async_save()
    assert fake.saves == []


async def test_a_save_is_queued_when_a_new_half_hour_starts_and_not_before():
    store, fake = _store()
    await store.async_load()
    store.record(_energy(), NOON - timedelta(seconds=30), NOON)
    store.record(_energy(), NOON, NOON + timedelta(seconds=30))
    assert len(fake.delayed) == 1  # the same half hour

    later = NOON + timedelta(minutes=30)
    store.record(_energy(), later - timedelta(seconds=30), later)
    assert len(fake.delayed) == 2


async def test_a_gap_is_not_booked_and_queues_no_save():
    store, fake = _store()
    await store.async_load()
    store.record(_energy(), NOON - timedelta(hours=2), NOON)
    assert fake.delayed == []
    assert store.history.get(NOON.date()) is None


async def test_the_queued_payload_is_the_versioned_history():
    store, fake = _store()
    await store.async_load()
    store.record(_energy(), NOON - timedelta(seconds=30), NOON)
    payload = fake.delayed[0]()
    assert payload["version"] == 1
    assert payload["days"][0]["date"] == "2026-06-01"


async def test_a_saved_history_is_read_back():
    day = SlotDay(date(2026, 5, 31), UTC)
    start = day.start + timedelta(hours=1)
    day.add(_energy(), start, start + timedelta(minutes=5))
    store, _ = _store({"version": 1, "days": [day.to_storage()]})
    await store.async_load()
    assert store.history.get(date(2026, 5, 31)).total("import") == 0.1


async def test_an_unreadable_file_starts_fresh_and_still_allows_saves():
    store, fake = _store(fail=True)
    await store.async_load()
    store.schedule_save()
    assert len(fake.delayed) == 1
    assert store.history.get(date(2026, 5, 31)) is None


async def test_an_unreadable_day_is_skipped_and_the_rest_kept():
    day = SlotDay(date(2026, 5, 31), UTC)
    store, _ = _store({"version": 1, "days": [{"date": "bad"}, day.to_storage()]})
    await store.async_load()
    assert store.history.skipped == 1
    assert store.history.get(date(2026, 5, 31)) is not None


async def test_a_charge_outside_zero_to_a_hundred_is_ignored():
    store, _ = _store()
    await store.async_load()
    store.record_soc(NOON, 140.0)
    store.record_soc(NOON, -3.0)
    assert store.history.get(NOON.date()) is None
    store.record_soc(NOON, 64.0)
    assert store.history.get(NOON.date()).soc_pct[24] == 64.0


async def test_an_explicit_save_writes_the_payload():
    store, fake = _store()
    await store.async_load()
    await store.async_save()
    assert fake.saves == [{"version": 1, "days": []}]
