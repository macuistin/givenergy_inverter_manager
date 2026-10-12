"""Whether the GivTCP version is one that resets entity ids.

GivTCP 3.6 and 3.6.1 deleted and recreated an entity whose discovery config changed, so Home
Assistant gave it the default entity id again and the entity lost its name and area. 3.6.2 fixed
it. Releases before 3.6 do not do this. 3.6 also mishandled charge slot 2 and PV-only inverters,
which 3.6.1 fixed. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import re

FIRST_AFFECTED_VERSION = "3.6"
FIXED_IN_VERSION = "3.6.2"

_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """The numbers at the start of a version such as `3.6.3`, `v3.6.3` or `3.6.3-beta`.

    None when there are no numbers, as for `unknown` or an empty state.
    """
    if not text:
        return None
    found = _NUMBERS.search(str(text))
    return tuple(int(part) for part in found.group().split(".")) if found else None


def _padded(numbers: tuple[int, ...], width: int) -> tuple[int, ...]:
    return numbers + (0,) * (width - len(numbers))


def resets_entity_ids(text: str | None) -> bool:
    """True only when the version is readable and from 3.6 up to, not including, 3.6.2.

    An unreadable version is not affected: a sensor that is missing or `unknown` must not raise
    a warning about a version nobody could read.
    """
    version = parse_version(text)
    if version is None:
        return False
    first = parse_version(FIRST_AFFECTED_VERSION)
    fixed = parse_version(FIXED_IN_VERSION)
    width = max(len(version), len(first), len(fixed))
    number = _padded(version, width)
    return _padded(first, width) <= number < _padded(fixed, width)
