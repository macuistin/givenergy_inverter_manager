"""lib/timeutil gives real elapsed time across a clock change, and the old path still works."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.givenergy_inverter_manager.core import timeutil as old_path
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


def test_the_old_core_path_re_exports_the_same_functions():
    for name in ("elapsed_seconds", "local_time_on", "real_time_after", "shift_real"):
        assert getattr(old_path, name) is getattr(timeutil, name)
