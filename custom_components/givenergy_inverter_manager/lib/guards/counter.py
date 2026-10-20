"""
counter.py: tell energy from a counter that jumped.

The inverter integration publishes cumulative energy for the day (solar, import, export, charge,
discharge, load and the AC charge counter). The integration uses them as they are for today and
books the rise of the AC charge counter on the longer periods. Upgrading GivTCP can change what
those counters hold: a Gateway's totals changed units, which makes a counter step by about a
thousand times, and a reset of a counter to another baseline looks like a rise.

A rise between two readings is energy only if the system could have delivered it in the time
between them. The most it can deliver is the inverter's maximum power times the elapsed time,
with a margin for a house that draws more than the inverter, and a small floor for the counter's
own rounding. A rise above that is not booked. A counter falling is the daily reset, and what it
reads after the fall is the energy since midnight, so it is held to the same limit.

A reading above anything one day could hold, or negative, is never trusted. A step of about a
thousand times is called a probable unit change in the log.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol, TypeVar

from ..tariff import CounterMemory
from .defaults import (
    COUNTER_RISE_FLOOR_KWH,
    COUNTER_RISE_MARGIN,
    COUNTER_UNIT_CHANGE_MIN_KWH,
    COUNTER_UNIT_CHANGE_RATIO,
)

_LOG = logging.getLogger(__name__)


class Readings(Protocol):
    """The readings screen() is given: a dataclass with the system's power and the counters."""

    inverter_max_w: float


RawT = TypeVar("RawT", bound=Readings)

OK = "ok"
FIRST = "first"
RESET = "reset"
TOO_LARGE = "too_large"
JUMP = "jump"
UNIT_CHANGE = "unit_change"
NEGATIVE = "negative"
RECOVERY = "recovery"

_SECONDS_PER_HOUR = 3600
_HOURS_PER_DAY = 24


@dataclass(frozen=True)
class Verdict:
    """What to do with a reading: whether to trust it, and how much energy it adds."""

    kind: str
    trusted: bool
    rise_kwh: float = 0.0


def allowed_rise_kwh(max_power_w: float, elapsed_s: float) -> float:
    """The most a counter can rise in *elapsed_s* seconds on a system of this power."""
    hours = max(0.0, elapsed_s) / _SECONDS_PER_HOUR
    return (max_power_w / 1000) * hours * COUNTER_RISE_MARGIN + COUNTER_RISE_FLOOR_KWH


def largest_day_kwh(max_power_w: float) -> float:
    """The most a daily counter can hold: full power for the whole day, with the margin."""
    return (max_power_w / 1000) * _HOURS_PER_DAY * COUNTER_RISE_MARGIN


def judge(
    previous_kwh: float | None, current_kwh: float, elapsed_s: float | None, max_power_w: float
) -> Verdict:
    """Judge one reading of a daily counter against the one before it.

    *elapsed_s* is None when the time since the previous reading is not known, as after a
    restart. The rate check is then skipped and the other checks still apply.
    """
    if current_kwh < 0:
        return Verdict(NEGATIVE, trusted=False)
    if current_kwh > largest_day_kwh(max_power_w):
        return Verdict(_big_kind(previous_kwh, current_kwh), trusted=False)
    if previous_kwh is None:
        return Verdict(FIRST, trusted=True, rise_kwh=current_kwh)
    fell = current_kwh < previous_kwh
    rise = current_kwh if fell else current_kwh - previous_kwh
    if elapsed_s is not None and rise > allowed_rise_kwh(max_power_w, elapsed_s):
        return Verdict(_big_kind(previous_kwh, current_kwh), trusted=False)
    if not fell and _is_unit_step(previous_kwh, current_kwh):
        return Verdict(UNIT_CHANGE, trusted=False)
    return Verdict(RESET if fell else OK, trusted=True, rise_kwh=rise)


def _is_unit_step(previous_kwh: float, current_kwh: float) -> bool:
    return (
        previous_kwh >= COUNTER_UNIT_CHANGE_MIN_KWH
        and current_kwh / previous_kwh >= COUNTER_UNIT_CHANGE_RATIO
    )


def _big_kind(previous_kwh: float | None, current_kwh: float) -> str:
    if previous_kwh is not None and _is_unit_step(previous_kwh, current_kwh):
        return UNIT_CHANGE
    return TOO_LARGE if previous_kwh is None else JUMP


# The raw readings that are screened, by the name each is remembered under.
_COUNTER_FIELDS: dict[str, str] = {
    "solar": "solar_energy_today_kwh",
    "import": "import_energy_today_kwh",
    "export": "export_energy_today_kwh",
    "charge": "charge_energy_today_kwh",
    "discharge": "discharge_energy_today_kwh",
    "load": "load_energy_today_kwh",
    "ac_charge": "ac_charge_energy_today_kwh",
}
AC_CHARGE = "ac_charge"


@dataclass(frozen=True)
class _Reading:
    """One counter's reading now, and what it is judged against."""

    name: str
    kwh: float
    now: datetime
    max_power_w: float


def screen(memory: CounterMemory, raw: RawT, now: datetime) -> RawT:
    """The readings with any counter that cannot be trusted left out (None).

    Each counter is judged against its previous reading. A counter that jumped is logged once,
    is not booked, and stays out of today's totals until it falls (the next daily reset), because
    after a step its absolute value is wrong for the rest of the day. The baseline moves to what
    it reads now, so the next reading continues from there. *raw* itself is not changed.
    """
    memory.ac_charge_rise_kwh = 0.0
    untrusted: dict[str, None] = {}
    for name, attribute in _COUNTER_FIELDS.items():
        current = getattr(raw, attribute)
        if current is None:
            continue
        if not _trust(memory, _Reading(name, float(current), now, raw.inverter_max_w)):
            untrusted[attribute] = None
    # Readings is a Protocol, so mypy cannot see that every implementation is a dataclass.
    return replace(raw, **untrusted) if untrusted else raw  # type: ignore[type-var]


def _trust(memory: CounterMemory, reading: _Reading) -> bool:
    name = reading.name
    previous, elapsed = _previous(memory, reading)
    verdict = _recovery(memory, reading, previous) or judge(
        previous, reading.kwh, elapsed, reading.max_power_w
    )
    memory.readings[name] = (reading.kwh, reading.now)
    if name == AC_CHARGE:
        memory.ac_charge_kwh = reading.kwh
    if verdict.kind in (RESET, RECOVERY):
        memory.distrusted.discard(name)  # the daily reset, or a spike that has gone again
    if not verdict.trusted:
        _note_jump(memory, reading, previous, verdict.kind)
        memory.distrusted.add(name)
        return False
    if name in memory.distrusted:
        return False  # after a step nothing is booked and today ignores it until it falls
    memory.last_trusted[name] = (reading.kwh, reading.now)
    if name == AC_CHARGE:
        memory.ac_charge_rise_kwh = verdict.rise_kwh
    return True


def _recovery(
    memory: CounterMemory, reading: _Reading, previous: float | None
) -> Verdict | None:
    """A counter that spiked and fell back to where it was: only what it added since is new.

    A fall after a jump is not the daily reset when it lands at or above the last good reading.
    """
    name = reading.name
    if name not in memory.distrusted or previous is None or reading.kwh >= previous:
        return None
    trusted = memory.last_trusted.get(name)
    if trusted is None or reading.kwh < trusted[0]:
        return None
    rise = reading.kwh - trusted[0]
    elapsed = (reading.now - trusted[1]).total_seconds()
    if elapsed < 0 or rise > allowed_rise_kwh(reading.max_power_w, elapsed):
        return None
    return Verdict(RECOVERY, trusted=True, rise_kwh=rise)


def _previous(memory: CounterMemory, reading: _Reading) -> tuple[float | None, float | None]:
    name = reading.name
    if name in memory.readings:
        value, at = memory.readings[name]
        elapsed = (reading.now - at).total_seconds()
        return value, elapsed if elapsed >= 0 else None
    if name == AC_CHARGE and memory.ac_charge_kwh:
        return memory.ac_charge_kwh, None  # the saved baseline has no time with it
    return None, None


def _note_jump(
    memory: CounterMemory, reading: _Reading, previous: float | None, kind: str
) -> None:
    if reading.name in memory.distrusted and kind != UNIT_CHANGE:
        return  # said once, when it first jumped
    before = "" if previous is None else f"{previous:g} to "
    cause = (
        "a probable unit change" if kind == UNIT_CHANGE else "more than the system could deliver"
    )
    _LOG.warning(
        "The %s energy counter went from %s%g kWh, %s. No energy is booked for the step, and "
        "the counter is left out of today's totals until it resets. After an upgrade of the "
        "inverter integration, check the counter's unit.",
        reading.name.replace("_", " "),
        before,
        reading.kwh,
        cause,
    )
