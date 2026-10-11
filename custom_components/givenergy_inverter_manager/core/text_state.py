"""
text_state.py — Fit a sentence into a Home Assistant sensor state.

Home Assistant keeps a state of at most STATE_MAX_LENGTH characters. A longer one is logged as
an error on every update and the state reads unknown. fit_state cuts a long sentence to fit,
at a sentence or clause boundary where it can, and marks the cut with an ellipsis. The
sensor keeps the full text in an attribute, which has no such limit.

Nothing here imports Home Assistant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..const import STATE_MAX_LENGTH

ELLIPSIS = "…"

# A cut that keeps less than this share of the room is worse than a cut mid-clause.
_MIN_KEPT_SHARE = 0.5

_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
_CLAUSE_END = re.compile(r"[,;:](?=\s|$)")
# A separator or an opening bracket that starts the next clause. The cut falls before it.
_CLAUSE_START = re.compile(r"\s+(?=[—–·-](?:\s|$)|\()")
_TRAILING_PUNCTUATION = " \t\r\n,;:.—–·-("


@dataclass(frozen=True)
class FittedText:
    """A text and the state that stands for it: the same text when it fits, else a cut of it."""

    state: str
    full: str

    @property
    def was_cut(self) -> bool:
        return self.state != self.full


def fit_state(text: str, limit: int = STATE_MAX_LENGTH) -> FittedText:
    """Return text as a state of at most limit characters, with the full text beside it.

    A text that fits is the state as it is. A longer one is cut: the state ends in an ellipsis,
    never splits a word and prefers the end of a sentence, then the end of a clause, then the
    end of a word. A single word longer than the limit has no boundary and is cut where it
    must be. Characters are counted, not bytes.
    """
    if len(text) <= limit:
        return FittedText(text, text)
    room = max(limit - len(ELLIPSIS), 0)
    head = _whole_words(text, room)
    kept = _boundary(head, room)
    return FittedText((head[:kept].rstrip(_TRAILING_PUNCTUATION) + ELLIPSIS)[:limit], text)


def _whole_words(text: str, room: int) -> str:
    """The longest start of text that fits in room and ends at the end of a word."""
    if text[room : room + 1].isspace():
        return text[:room]
    window = text[:room]
    last_space = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
    return window[:last_space] if last_space > 0 else window


def _boundary(head: str, room: int) -> int:
    """Where to cut head: the last sentence end, else clause end, else its whole length."""
    floor = int(room * _MIN_KEPT_SHARE)
    for ends in (_ends_of(_SENTENCE_END, head), _ends_of(_CLAUSE_END, head), _starts_of(head)):
        late_enough = [end for end in ends if end >= floor]
        if late_enough:
            return late_enough[-1]
    return len(head)


def _ends_of(pattern: re.Pattern[str], head: str) -> list[int]:
    return [match.end() for match in pattern.finditer(head)]


def _starts_of(head: str) -> list[int]:
    return [match.start() for match in _CLAUSE_START.finditer(head)]
