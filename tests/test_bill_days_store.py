"""The bill period's rows in the accumulation store: added at midnight, archived at the bill day."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationStore,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.core.bill_days import tariff_snapshot
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg

BILL_DAY = 16
OLD = tariff_snapshot(_nightboost_cfg())
NEW = {**OLD, "base_rate": 0.40}


def _store() -> AccumulationStore:
    with patch(
        "custom_components.givenergy_inverter_manager.accumulation._create_store",
        return_value=MagicMock(),
    ):
        store = AccumulationStore(MagicMock(), BILL_DAY)
    store.state.month_start_iso = datetime(2026, 9, 16).isoformat()
    return store


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day)


def _use(store: AccumulationStore, kwh: float) -> None:
    for acc in (store.state.today, store.state.month):
        acc.import_kwh += kwh
        acc.import_kwh_by_period["Day"] = acc.import_kwh_by_period.get("Day", 0.0) + kwh
        acc.import_cost_by_period["Day"] = acc.import_cost_by_period.get("Day", 0.0) + kwh * 0.4


def _end_of(store: AccumulationStore, day: date, tariff=OLD) -> None:
    """Midnight that closes *day*."""
    store.on_midnight(_midnight(day + timedelta(days=1)), tariff)


class TestRowsAreAddedAtMidnight:
    def test_the_finished_day_becomes_a_row(self):
        store = _store()
        _use(store, 5.0)

        _end_of(store, date(2026, 10, 13))

        [row] = store.state.bill_days
        assert row["date"] == "2026-10-13"
        assert row["import_kwh"] == 5.0
        assert row["tariff"] == OLD

    def test_a_day_with_nothing_recorded_adds_no_row(self):
        store = _store()

        _end_of(store, date(2026, 10, 13))

        assert store.state.bill_days == []

    def test_the_tariff_is_recorded_when_it_changes_and_not_otherwise(self):
        store = _store()
        for day, tariff in ((17, OLD), (18, OLD), (19, NEW), (20, NEW)):
            _use(store, 1.0)
            _end_of(store, date(2026, 10, day), tariff)

        assert ["tariff" in row for row in store.state.bill_days] == [True, False, True, False]

    def test_a_midnight_replayed_after_a_restart_carries_the_last_tariff(self):
        store = _store()
        _use(store, 1.0)
        _end_of(store, date(2026, 10, 17))
        _use(store, 1.0)

        store.on_midnight(_midnight(date(2026, 10, 19)), None)

        assert [row["date"] for row in store.state.bill_days] == ["2026-10-17", "2026-10-18"]
        assert "tariff" not in store.state.bill_days[1]


class TestTheBillPeriodEnds:
    def test_the_rows_go_into_the_snapshot_and_the_list_starts_again(self):
        store = _store()
        for day in (14, 15):
            _use(store, 2.0)
            _end_of(store, date(2026, 10, day))

        # The midnight that opens the 16th closes the 15th, the last day of the period.
        [snap] = store.state.monthly_snapshots
        assert [row["date"] for row in snap["days"]] == ["2026-10-14", "2026-10-15"]
        assert snap["period_start"] == datetime(2026, 9, 16).isoformat()
        assert snap["period_end"] == "2026-10-15"
        assert store.state.bill_days == []

    def test_the_day_that_closes_the_period_is_in_that_period(self):
        store = _store()
        _use(store, 3.0)

        _end_of(store, date(2026, 10, 15))

        assert store.state.monthly_snapshots[0]["days"][-1]["date"] == "2026-10-15"
        assert store.state.bill_days == []

    def test_the_next_period_starts_with_the_first_day_of_it(self):
        store = _store()
        _use(store, 3.0)
        _end_of(store, date(2026, 10, 15))
        _use(store, 1.0)

        _end_of(store, date(2026, 10, 16), NEW)

        assert [row["date"] for row in store.state.bill_days] == ["2026-10-16"]
        assert store.state.bill_days[0]["tariff"] == NEW

    def test_the_snapshot_keeps_its_totals_beside_the_days(self):
        store = _store()
        _use(store, 3.0)

        _end_of(store, date(2026, 10, 15))

        snap = store.state.monthly_snapshots[0]
        assert snap["import_kwh"] == 3.0
        assert snap["import_cost_by_period"] == {"Day": 3.0 * 0.4}

    def test_twelve_periods_are_kept_with_their_days(self):
        store = _store()
        for month in range(1, 14):
            _use(store, 1.0)
            store.on_midnight(_midnight(date(2026 + month // 13, month % 12 + 1, 16)), OLD)

        assert len(store.state.monthly_snapshots) == 12
        assert all("days" in snap for snap in store.state.monthly_snapshots)


class TestPersistence:
    def test_rows_survive_a_save_and_a_load(self):
        store = _store()
        _use(store, 4.0)
        _end_of(store, date(2026, 10, 13))

        restored = _deserialize(_serialize(store.state))

        assert restored.bill_days == store.state.bill_days

    def test_an_older_store_with_no_rows_loads_with_none(self):
        payload = _serialize(_store().state)
        payload.pop("bill_days")

        assert _deserialize(payload).bill_days == []

    def test_an_older_snapshot_with_no_days_still_loads(self):
        store = _store()
        store.state.monthly_snapshots = [{"import_kwh": 9.0}]

        assert _deserialize(_serialize(store.state)).monthly_snapshots == [{"import_kwh": 9.0}]

    def test_the_accumulator_keeps_its_per_period_kwh(self):
        store = _store()
        _use(store, 4.0)

        restored = _deserialize(_serialize(store.state))

        assert restored.month.import_kwh_by_period == {"Day": 4.0}
        assert restored.today == store.state.today
        assert restored.today != EnergyAccumulator()
