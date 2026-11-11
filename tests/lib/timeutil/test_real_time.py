# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""lib/timeutil gives real elapsed time across a clock change."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.givenergy_inverter_manager.lib import timeutil

DUBLIN = ZoneInfo("Europe/Dublin")


def test_elapsed_seconds_counts_the_hour_lost_to_spring_forward():
    before = datetime(2026, 3, 29, 0, 30, tzinfo=DUBLIN)
    after = datetime(2026, 3, 29, 2, 30, tzinfo=DUBLIN)

    assert timeutil.elapsed_seconds(before, after) == 3600.0


def test_shift_real_moves_by_real_time_in_the_same_timezone():
    before = datetime(2026, 3, 29, 0, 30, tzinfo=DUBLIN)

    moved = timeutil.shift_real(before, timedelta(hours=1))

    assert moved == datetime(2026, 3, 29, 2, 30, tzinfo=DUBLIN)
    assert moved.tzinfo == DUBLIN



def test_naive_times_are_subtracted_and_moved_as_they_are():
    start = datetime(2026, 3, 29, 0, 30)

    assert timeutil.elapsed_seconds(start, datetime(2026, 3, 29, 2, 30)) == 7200.0
    assert timeutil.shift_real(start, timedelta(hours=1)) == datetime(2026, 3, 29, 1, 30)


def test_local_time_on_gives_the_wall_clock_time_on_the_same_day_and_pass():
    second_pass = datetime(2026, 10, 25, 1, 30, tzinfo=DUBLIN, fold=1)

    at = timeutil.local_time_on(second_pass, time(1, 45))

    assert (at.date(), at.time(), at.fold, at.tzinfo) == (second_pass.date(), time(1, 45), 1, DUBLIN)
