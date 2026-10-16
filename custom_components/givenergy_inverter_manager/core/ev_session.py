"""
ev_session.py: the energy and cost of one EV charging session, and the last few finished ones.

A session starts on the first cycle the charger reads plugged in and ends on the first cycle it
reads unplugged. That is the span the charger's own session energy counts: a Zappi's charge
added this session and a GivEnergy charger's session energy both start from zero at plug-in.
A drop in that counter is not used as a boundary, because an unavailable counter reads zero.
A charger state of unknown says nothing about the plug, so it neither starts nor ends a session.

Each cycle adds the EV energy and EV cost that today's EV totals counted for the same step
(core/engine.py), so a session that crosses midnight costs exactly what the two days' EV cost
counted for its energy. Solar energy that reached the car costs nothing there, and so here.

A finished session that delivered no energy is not kept. The last EV_RECENT_SESSIONS_MAX
finished sessions are kept, newest first.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ..const import EV_RECENT_SESSIONS_MAX
from ..discovery import EVChargerState

_STORED_DECIMALS = 6
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_TABLE_HEADER = ("| Charge | Energy | Cost | Per kWh |", "|:--|--:|--:|--:|")
NO_FINISHED_SESSIONS = "No finished charges yet."
SOLAR_LABEL = "solar"


@dataclass
class EVSession:
    """One plug-in to unplug span: when it ran, the energy it delivered and what it cost."""

    start: datetime
    end: datetime | None = None
    energy_kwh: float = 0.0
    cost: float = 0.0

    @property
    def per_kwh(self) -> float | None:
        """Cost per kWh, None before the session has delivered any energy."""
        return self.cost / self.energy_kwh if self.energy_kwh > 0 else None

    def to_storage(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end is not None else None,
            "energy_kwh": round(self.energy_kwh, _STORED_DECIMALS),
            "cost": round(self.cost, _STORED_DECIMALS),
        }


@dataclass
class EVSessionLog:
    """The running session, the finished ones newest first and the plug state last read."""

    current: EVSession | None = None
    recent: list[EVSession] = field(default_factory=list)
    plugged_in: bool = False

    @property
    def is_empty(self) -> bool:
        """True while there is nothing worth storing."""
        return self.current is None and not self.recent and not self.plugged_in

    @property
    def latest(self) -> EVSession | None:
        """The running session, else the last finished one, None before the first session."""
        if self.current is not None:
            return self.current
        return self.recent[0] if self.recent else None

    def to_storage(self) -> dict:
        return {
            "current": self.current.to_storage() if self.current is not None else None,
            "recent": [session.to_storage() for session in self.recent],
            "plugged_in": self.plugged_in,
        }

    @classmethod
    def from_storage(cls, stored: object) -> EVSessionLog:
        """The log from its stored form. A damaged entry is skipped, a damaged log starts empty."""
        if not isinstance(stored, dict):
            return cls()
        entries = stored.get("recent")
        recent = [s for s in map(_restore_session, entries or ()) if s is not None]
        current = _restore_session(stored.get("current"))
        return cls(
            current=current if current is not None and current.end is None else None,
            recent=recent[:EV_RECENT_SESSIONS_MAX],
            plugged_in=stored.get("plugged_in") is True,
        )


@dataclass(frozen=True)
class EVSessionStep:
    """One cycle: the time, the charger's state and the EV energy and cost of the step."""

    now: datetime
    charger_state: EVChargerState
    energy_kwh: float = 0.0
    cost: float = 0.0


def track_session(log: EVSessionLog, step: EVSessionStep) -> None:
    """Start, add to or end the session for one cycle. Mutates log."""
    if step.charger_state is EVChargerState.UNKNOWN:
        _add_step(log, step)
        return
    plugged_in = step.charger_state is not EVChargerState.DISCONNECTED
    if plugged_in and log.current is None:
        log.current = EVSession(start=step.now)
    _add_step(log, step)
    if not plugged_in and log.current is not None:
        _finish(log, step.now)
    log.plugged_in = plugged_in


def _add_step(log: EVSessionLog, step: EVSessionStep) -> None:
    if log.current is None:
        return
    log.current.energy_kwh += max(0.0, step.energy_kwh)
    log.current.cost += max(0.0, step.cost)


def _finish(log: EVSessionLog, now: datetime) -> None:
    session, log.current = log.current, None
    if session is None or session.energy_kwh <= 0:
        return
    session.end = now
    log.recent = [session, *log.recent][:EV_RECENT_SESSIONS_MAX]


def _restore_session(entry: object) -> EVSession | None:
    """A session from its stored form, None when the entry is damaged."""
    if not isinstance(entry, dict):
        return None
    try:
        start = datetime.fromisoformat(entry["start"])
        end = datetime.fromisoformat(entry["end"]) if entry.get("end") is not None else None
        energy_kwh = float(entry.get("energy_kwh", 0.0))
        cost = float(entry.get("cost", 0.0))
    except KeyError, TypeError, ValueError:
        return None
    return EVSession(start=start, end=end, energy_kwh=energy_kwh, cost=cost)


# ── The recent charges table ──────────────────────────────────────────────────


def _day_and_time(moment: datetime) -> str:
    return f"{moment.day} {_MONTHS[moment.month - 1]}, {moment:%H:%M}"


def _span(session: EVSession) -> str:
    """When the session ran. The end date shows only when it is more than a day after the start."""
    end = session.end if session.end is not None else session.start
    if (end.date() - session.start.date()).days > 1:
        return f"{_day_and_time(session.start)} to {_day_and_time(end)}"
    return f"{_day_and_time(session.start)} to {end:%H:%M}"


def _per_kwh_text(session: EVSession, symbol: str) -> str:
    per_kwh = session.per_kwh
    if per_kwh is None:
        return "-"
    if round(session.cost, 2) == 0:
        return SOLAR_LABEL
    return f"{symbol}{per_kwh:.3f}"


def _table_row(session: EVSession, symbol: str) -> str:
    cells = (
        _span(session),
        f"{session.energy_kwh:.1f} kWh",
        f"{symbol}{session.cost:.2f}",
        _per_kwh_text(session, symbol),
    )
    return "| " + " | ".join(cells) + " |"


def recent_table(sessions: Sequence[EVSession], symbol: str) -> str:
    """The finished sessions as a markdown table for the dashboard, or one sentence when none."""
    if not sessions:
        return NO_FINISHED_SESSIONS
    return "\n".join([*_TABLE_HEADER, *(_table_row(s, symbol) for s in sessions)])
