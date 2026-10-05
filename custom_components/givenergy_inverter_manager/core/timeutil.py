"""
timeutil.py — duration maths that stays correct across a clock change.

Python subtracts two aware datetimes that share the same tzinfo as plain
wall-clock time and ignores the UTC offset. Across a daylight saving change
that is an hour out. Convert both ends to UTC before subtracting.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


def elapsed_seconds(start: datetime, end: datetime) -> float:
    """Real seconds from start to end, negative when end is earlier.

    Naive datetimes have no offset to apply and are subtracted as they are.
    """
    if start.tzinfo is None or end.tzinfo is None:
        return (end - start).total_seconds()
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()


def local_time_on(day: datetime, at: time) -> datetime:
    """The wall-clock time *at* on the date of *day*, in the timezone of *day*.

    Keeps day.fold, so a time in the repeated hour of a fall-back change means the
    same pass as *day*. A time in the skipped hour of a spring-forward change does
    not exist. With fold=0 it is read with the offset in force before the change,
    so it lands on the instant an hour later on the wall clock, and never raises.
    """
    return datetime.combine(day.date(), at, tzinfo=day.tzinfo).replace(fold=day.fold)


def real_time_after(start: datetime, delta: timedelta) -> datetime:
    """The instant *delta* of real time after *start*, in UTC.

    Adding to an aware datetime moves the wall clock, which is wrong across a
    clock change. The result is in UTC so that comparing it with a local
    datetime compares real instants, not wall-clock readings.
    """
    return start.astimezone(timezone.utc) + delta
