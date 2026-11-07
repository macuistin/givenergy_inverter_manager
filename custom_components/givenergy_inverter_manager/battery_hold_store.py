"""battery_hold_store.py: the pause a battery hold changed, saved until the hold is ended.

A hold writes over the inverter's pause window, which repeats every day. If Home Assistant stops
during a hold, the original pause is in this store, so the next start can write it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .core.ev_battery_hold import HoldRecord
from .logging import get_logger

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOG = get_logger(__name__)
_STORAGE_KEY = "givenergy_inverter_manager.battery_hold"
_STORAGE_VERSION = 1


def _create_store(hass: HomeAssistant) -> Store[dict[str, Any]]:
    from homeassistant.helpers.storage import Store  # lazy: not available in the unit tests

    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


class BatteryHoldStore:
    """Saves and reads the one record of a hold in progress."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = _create_store(hass)

    async def async_load(self) -> HoldRecord | None:
        """The saved record, None when there is none or it cannot be read."""
        try:
            data = await self._store.async_load()
        except Exception as err:  # a store boundary: a bad file must not stop setup
            _LOG.warning("Could not read the saved battery hold: %s", err)
            return None
        return HoldRecord.from_dict(data) if data else None

    async def async_save(self, record: HoldRecord | None) -> None:
        """Save the record now, or clear it when *record* is None."""
        try:
            await self._store.async_save(record.as_dict() if record else {})
        except Exception as err:  # a store boundary
            _LOG.warning("Could not save the battery hold: %s", err)
