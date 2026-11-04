"""One local day in half-hour slots: boundaries, clock changes, coverage and storage."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff.slot_history import SlotHistory
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay, SlotEnergy
from custom_components.givenergy_inverter_manager.lib.timeutil import shift_real

LONDON = ZoneInfo("Europe/London")


def _imp(kwh: float) -> SlotEnergy:
    return SlotEnergy(flows={"import": kwh})


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LONDON)


def test_a_normal_day_has_48_slots_and_a_clock_change_day_has_46_or_50() -> None:
    assert SlotDay(date(2026, 6, 1), LONDON).slot_count == 48
    assert SlotDay(date(2026, 3, 29), LONDON).slot_count == 46
    assert SlotDay(date(2026, 10, 25), LONDON).slot_count == 50


def test_an_interval_inside_one_slot_books_all_of_it_there() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    day.add(_imp(0.2), _at(day.day, 12, 1), _at(day.day, 12, 6))
    assert day.flows["import"][24] == pytest.approx(0.2)
    assert day.total("import") == pytest.approx(0.2)


def test_an_interval_over_a_slot_boundary_splits_by_time() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    day.add(_imp(1.0), _at(day.day, 12, 28), _at(day.day, 12, 33))
    assert day.flows["import"][24] == pytest.approx(0.4)
    assert day.flows["import"][25] == pytest.approx(0.6)
    assert day.seconds[24] == pytest.approx(120)
    assert day.seconds[25] == pytest.approx(180)


def test_slots_after_the_spring_forward_hour_are_counted_in_real_time() -> None:
    day = SlotDay(date(2026, 3, 29), LONDON)
    day.add(_imp(1.0), _at(day.day, 3, 0), _at(day.day, 3, 30))
    # The clock skips 01:00 to 02:00, so 03:00 BST is only the 3rd real hour: slot 4 (0-based).
    assert day.flows["import"][4] == pytest.approx(1.0)


def test_the_repeated_hour_has_its_own_slots_on_a_fall_back_day() -> None:
    day = SlotDay(date(2026, 10, 25), LONDON)
    first_pass = datetime(2026, 10, 25, 1, 15, tzinfo=LONDON, fold=0)
    second_pass = datetime(2026, 10, 25, 1, 15, tzinfo=LONDON, fold=1)
    day.add(_imp(0.5), first_pass, shift_real(first_pass, timedelta(minutes=5)))
    day.add(_imp(0.7), second_pass, shift_real(second_pass, timedelta(minutes=5)))
    assert day.flows["import"][2] == pytest.approx(0.5)
    assert day.flows["import"][4] == pytest.approx(0.7)


def test_coverage_tells_no_data_from_no_use() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    assert day.coverage == 0
    day.add(_imp(0.0), _at(day.day, 0, 0), _at(day.day, 12, 0))
    assert day.coverage == pytest.approx(0.5)


@pytest.mark.parametrize(
    "energy",
    [
        SlotEnergy(flows={"nope": 1.0}),
        SlotEnergy(flows={"import": -0.1}),
        SlotEnergy(flows={"import": float("nan")}),
        SlotEnergy(loads={"Heat Pump": 1.0}),
        SlotEnergy(loads={"ev": -1.0}),
    ],
)
def test_bad_figures_are_refused_and_book_nothing(energy: SlotEnergy) -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    with pytest.raises(ValueError):
        day.add(energy, _at(day.day, 1), _at(day.day, 1, 5))
    assert day.total("import") == 0 and day.coverage == 0


def test_an_interval_outside_the_day_is_refused() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    with pytest.raises(ValueError):
        day.add(_imp(1.0), _at(day.day, 23, 55), _at(day.day, 23, 55) + timedelta(hours=1))


def test_storage_round_trips_to_the_watt_hour() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    energy = SlotEnergy(flows={"import": 0.1234, "solar": 2.0}, loads={"house": 0.3, "heat_pump": 1.5})
    day.add(energy, _at(day.day, 9, 0), _at(day.day, 9, 20))
    day.set_soc(_at(day.day, 9, 10), 55.04)
    again = SlotDay.from_storage(day.to_storage(), LONDON)
    assert again.flows["import"][18] == pytest.approx(0.123)
    assert again.flows["solar"][18] == pytest.approx(2.0)
    assert again.loads["house"][18] == pytest.approx(0.3)
    assert again.loads["heat_pump"][18] == pytest.approx(1.5)
    assert again.soc_pct[18] == 55.0 and again.soc_pct[17] is None
    assert again.seconds[18] == 1200


@pytest.mark.parametrize(
    "broken",
    [{}, {"version": 1, "date": "x"}, {"version": 1, "date": "2026-06-01"}, {"version": 2}],
)
def test_unreadable_stored_days_are_refused(broken: dict) -> None:
    with pytest.raises(ValueError):
        SlotDay.from_storage(broken, LONDON)


def test_a_stored_day_with_the_wrong_slot_count_is_refused() -> None:
    stored = SlotDay(date(2026, 6, 1), LONDON).to_storage()
    stored["seconds"] = stored["seconds"][:-1]
    with pytest.raises(ValueError):
        SlotDay.from_storage(stored, LONDON)


def test_a_day_saved_under_another_time_zone_is_refused() -> None:
    stored = SlotDay(date(2026, 6, 1), ZoneInfo("Europe/Dublin")).to_storage()
    stored["start"] = "2026-06-01T00:00:00+02:00"
    with pytest.raises(ValueError):
        SlotDay.from_storage(stored, ZoneInfo("Europe/Dublin"))


def test_a_state_of_charge_must_be_a_percentage_inside_the_day() -> None:
    day = SlotDay(date(2026, 6, 1), LONDON)
    for percent in (-1, 101):
        with pytest.raises(ValueError):
            day.set_soc(_at(day.day, 1), percent)
    with pytest.raises(ValueError):
        day.set_soc(_at(day.day, 1) + timedelta(days=1), 50)


def test_history_notes_the_state_of_charge_by_slot() -> None:
    history = SlotHistory(LONDON)
    history.record_soc(_at(date(2026, 6, 1), 12, 40), 80.0)
    assert history.get(date(2026, 6, 1)).soc_pct[25] == 80.0  # type: ignore[union-attr]


def test_history_splits_an_interval_across_midnight_by_time() -> None:
    history = SlotHistory(LONDON)
    start = datetime(2026, 6, 1, 23, 58, tzinfo=LONDON)
    assert history.record(_imp(1.0), start, start + timedelta(minutes=4)) is True
    assert history.get(date(2026, 6, 1)).total("import") == pytest.approx(0.5)  # type: ignore[union-attr]
    assert history.get(date(2026, 6, 2)).total("import") == pytest.approx(0.5)  # type: ignore[union-attr]


def test_history_does_not_book_a_gap_or_an_empty_interval() -> None:
    history = SlotHistory(LONDON)
    start = _at(date(2026, 6, 1), 10)
    assert history.record(_imp(1.0), start, start + timedelta(minutes=31)) is False
    assert history.record(_imp(1.0), start, start) is False
    assert history.between(date(2026, 6, 1), date(2026, 6, 1)) == []


def test_history_drops_days_past_the_retention() -> None:
    history = SlotHistory(LONDON, retention_days=3)
    for offset in range(5):
        start = _at(date(2026, 6, 1) + timedelta(days=offset), 10)
        history.record(_imp(1.0), start, start + timedelta(minutes=5))
    kept = [d.day for d in history.between(date(2026, 6, 1), date(2026, 6, 30))]
    assert kept == [date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)]


def test_history_restores_what_it_stored_and_counts_what_it_skips() -> None:
    history = SlotHistory(LONDON)
    start = _at(date(2026, 6, 1), 10)
    history.record(_imp(0.5), start, start + timedelta(minutes=5))
    stored = [*history.to_storage(), {"date": "bad"}, "junk"]
    again = SlotHistory(LONDON)
    again.restore(stored)
    assert again.skipped == 2
    assert again.get(date(2026, 6, 1)).total("import") == pytest.approx(0.5)  # type: ignore[union-attr]


def test_the_inverters_day_total_sits_beside_the_slots_and_the_gap_is_shown():
    day = SlotDay(date(2026, 6, 1), LONDON)
    day.add(_imp(1.0), _at(day.day, 9, 0), _at(day.day, 9, 20))
    assert day.gap_kwh("import") is None  # no counter yet

    day.note_counters({"import": 1.3})
    assert day.gap_kwh("import") == pytest.approx(0.3)
    day.note_counters({"import": 1.5})  # a later reading replaces the earlier one
    assert day.gap_kwh("import") == pytest.approx(0.5)
    assert day.gap_kwh("export") is None


@pytest.mark.parametrize("readings", [{"nope": float("nan")}, {"import": -1.0}, {"Bad Name": 1.0}])
def test_bad_day_totals_are_refused(readings):
    day = SlotDay(date(2026, 6, 1), LONDON)
    with pytest.raises(ValueError):
        day.note_counters(readings)
    assert day.counters_kwh == {}


def test_the_day_totals_round_trip_and_an_older_day_without_them_still_loads():
    day = SlotDay(date(2026, 6, 1), LONDON)
    day.note_counters({"import": 12.3456, "house": 20.0})
    stored = day.to_storage()
    assert stored["counters_wh"] == {"import": 12346, "house": 20000}
    assert SlotDay.from_storage(stored, LONDON).counters_kwh["import"] == pytest.approx(12.346)

    del stored["counters_wh"]
    assert SlotDay.from_storage(stored, LONDON).counters_kwh == {}


def test_the_summary_lists_the_newest_days_with_the_gap_per_series():
    history = SlotHistory(LONDON)
    for offset in range(3):
        start = _at(date(2026, 6, 1) + timedelta(days=offset), 10)
        history.record(SlotEnergy(flows={"import": 0.5}), start, start + timedelta(minutes=5))
    history.note_counters(date(2026, 6, 3), {"import": 0.75})

    rows = history.summary(days=2)
    assert [r["date"] for r in rows] == ["2026-06-03", "2026-06-02"]
    assert rows[0]["series"]["import"] == {"slots_kwh": 0.5, "inverter_kwh": 0.75, "gap_kwh": 0.25}
    assert rows[1]["series"]["import"]["inverter_kwh"] is None
    assert rows[1]["coverage"] > 0
    assert "export" not in rows[0]["series"]  # nothing recorded and no counter
