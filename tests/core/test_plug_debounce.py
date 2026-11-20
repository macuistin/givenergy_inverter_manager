"""The plug state the charge plan sees ignores a short drop in the charger's reading."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.givenergy_inverter_manager.core.plug_debounce import PlugDebounce

T0 = datetime(2031, 3, 4, 2, 34, tzinfo=timezone.utc)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_the_first_reading_is_taken_as_it_is():
    assert PlugDebounce(600).update(False, T0) is False
    assert PlugDebounce(600).update(True, T0) is True


def test_plugging_in_counts_at_once():
    debounce = PlugDebounce(600)
    debounce.update(False, T0)
    assert debounce.update(True, at(1)) is True


def test_a_short_unplugged_reading_is_ignored():
    debounce = PlugDebounce(600)
    debounce.update(True, T0)
    assert debounce.update(False, at(60)) is True
    assert debounce.update(True, at(120)) is True
    assert debounce.update(False, at(180)) is True


def test_unplugged_for_the_whole_confirm_time_counts():
    debounce = PlugDebounce(600)
    debounce.update(True, T0)
    assert debounce.update(False, at(10)) is True
    assert debounce.update(False, at(609)) is True
    assert debounce.update(False, at(610)) is False
    assert debounce.update(False, at(700)) is False


def test_a_reading_that_returns_restarts_the_wait():
    debounce = PlugDebounce(600)
    debounce.update(True, T0)
    debounce.update(False, at(10))
    debounce.update(True, at(500))
    assert debounce.update(False, at(520)) is True
    assert debounce.update(False, at(1000)) is True
    assert debounce.update(False, at(1120)) is False
