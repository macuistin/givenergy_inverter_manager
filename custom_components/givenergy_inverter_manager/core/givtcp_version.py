"""Whether the GivTCP version is older than the oldest release this integration is safe on.

3.6 and 3.6.1 reset entity ids and mis-handle charge slot 2 and PV-only inverters. 3.6.2 fixed
all three. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import re

MINIMUM_GIVTCP_VERSION = "3.6.2"

_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """The numbers at the start of a version such as `3.6.3`, `v3.6.3` or `3.6.3-beta`.

    None when there are no numbers, as for `unknown` or an empty state.
    """
    if not text:
        return None
    found = _NUMBERS.search(str(text))
    return tuple(int(part) for part in found.group().split(".")) if found else None


def is_older_than_minimum(text: str | None) -> bool:
    """True only when the version is readable and older than the minimum.

    An unreadable version is not older: a sensor that is missing or `unknown` must not raise a
    warning about a version nobody could read.
    """
    version = parse_version(text)
    if version is None:
        return False
    minimum = parse_version(MINIMUM_GIVTCP_VERSION)
    width = max(len(version), len(minimum))
    return version + (0,) * (width - len(version)) < minimum + (0,) * (width - len(minimum))
