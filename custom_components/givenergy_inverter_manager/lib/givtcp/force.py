"""
force.py: GivTCP's timed force charge and force export.

GivTCP can charge or export for a set time and then put the old schedule, rates and target
back itself. Two entities do it for each: a select of preset durations and a number of
minutes for longer ones.

The option names are not documented by GivTCP, so nothing is assumed about them. A preset
is read from the select's own `options` (a leading number, with an hour or minute unit). A
request longer than every preset goes to the number entity when it can hold it. Otherwise the
longest preset that does not run past the time asked for is chosen. Nothing is sent when no
entity can hold a request that short, so a force is never longer than asked.

Written for the force-charge and force-export entities as other projects describe them
(`force_charge`, `force_charge_num`, `force_export`, `force_export_num`). Not checked against
GivTCP's source or a real inverter.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ._entity import GetState, attribute_limit, listed_options, squash, usable
from .controls import control_entity
from .model import Force
from .status import WriteStatus
from .writer import GivTCPWriter

_DURATION = re.compile(r"^\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]*)")
_CANCEL = frozenset({"cancel", "stop", "normal", "off", "none", "disabled"})
_HOUR_UNITS = ("h", "hr", "hrs", "hour", "hours")


def option_minutes(option: str) -> int | None:
    """The minutes a preset stands for ('30 minutes', '1 hour', '90'), None if it is not one."""
    match = _DURATION.match(option.casefold())
    if match is None:
        return None
    amount = float(match["amount"])
    return round(amount * 60) if match["unit"] in _HOUR_UNITS else round(amount)


class GivTCPForce:
    """Starts and cancels a timed force charge or force export."""

    def __init__(self, writer: GivTCPWriter, get_state: GetState) -> None:
        self._writer = writer
        self._get_state = get_state

    def _entities(self, cfg: Mapping[str, Any], force: Force) -> tuple[str | None, str | None]:
        return (
            control_entity(cfg, "select", f"_{force.value}"),
            control_entity(cfg, "number", f"_{force.value}_num"),
        )

    def read_remaining(self, cfg: Mapping[str, Any], force: Force) -> str | None:
        """The select's current option, None when it is not published or unusable."""
        select, _ = self._entities(cfg, force)
        return usable(self._get_state(select)) if select else None

    async def start(self, cfg: Mapping[str, Any], force: Force, minutes: int) -> WriteStatus:
        """Force for at most *minutes*. REFUSED when no entity can hold a request that short.

        A request longer than every preset goes to the minutes entity when it can hold it.
        Otherwise the longest preset that fits is used, so a force is never longer than asked.
        """
        if minutes <= 0:
            return WriteStatus.REFUSED
        select, number = self._entities(cfg, force)
        presets = self._presets(select)
        longest = max((m for m, _ in presets), default=0)
        if minutes > longest and number and self._number_holds(number, minutes):
            return await self._writer.set_number(number, minutes, f"{force.value} minutes")
        fits = [(m, o) for m, o in presets if m <= minutes]
        if fits and select:
            return await self._writer.set_select(select, max(fits)[1], force.value)
        return WriteStatus.REFUSED

    def _number_holds(self, number: str, minutes: int) -> bool:
        state = self._get_state(number)
        if state is None:
            return False
        limit = attribute_limit(state, "max")
        return limit is None or minutes <= limit

    async def cancel(self, cfg: Mapping[str, Any], force: Force) -> WriteStatus:
        """End a running force. GivTCP restores the schedule it saved when it started."""
        select, number = self._entities(cfg, force)
        state = self._get_state(select) if select else None
        options = listed_options(state)
        if select and options:
            option = next((o for o in options if squash(o) in _CANCEL), None)
            if option is not None:
                return await self._writer.set_select(select, option, f"cancel {force.value}")
        if number and self._get_state(number) is not None:
            return await self._writer.set_number(number, 0, f"cancel {force.value}")
        return WriteStatus.REFUSED

    def _presets(self, select: str | None) -> list[tuple[int, str]]:
        """The (minutes, option) pairs the select offers, leaving out 'Normal' and the like."""
        options = listed_options(self._get_state(select)) if select else None
        return [(m, o) for o in options or [] if (m := option_minutes(o)) is not None and m > 0]
