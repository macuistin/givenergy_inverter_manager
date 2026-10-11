"""
hacs.py - the one optional custom card from HACS, and the fallback used when it is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ..logging import get_logger

_LOG = get_logger(__name__)


# ── HACS cards ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HacsCard:
    """A custom card from HACS, and where to get it."""

    name: str
    url: str

    @property
    def card_type(self) -> str:
        return f"custom:{self.name}"


POWER_FLOW_CARD = HacsCard("power-flow-card-plus", "https://github.com/flixlix/power-flow-card-plus")


class HacsCards:
    """Says whether a HACS card is installed, from the Lovelace resources the host reported."""

    def __init__(self, resources: list[str] | None) -> None:
        self._resources = resources

    def installed(self, card: HacsCard) -> bool:
        """True when the Lovelace resources list this card.

        Unreadable resources (None) count as not installed. The dashboard works with core
        cards alone, so a card is used only when it is seen to be there.
        """
        if self._resources is None:
            return False
        return any(card.name in url.lower() for url in self._resources)


async def async_lovelace_resource_urls(hass: HomeAssistant) -> list[str] | None:
    """Return the URLs of the Lovelace resources, or None when they cannot be read.

    HACS cards register here (storage mode) or in configuration.yaml (YAML mode).
    A card loaded some other way, for example by another integration, is not listed.
    """
    data = hass.data.get("lovelace")
    resources = (
        data.get("resources") if isinstance(data, dict) else getattr(data, "resources", None)
    )
    if resources is None:
        return None
    try:
        await resources.async_get_info()
        return [str(item.get("url", "")) for item in resources.async_items() or []]
    except Exception as err:  # noqa: BLE001
        _LOG.debug("Could not read Lovelace resources: %s", err)
        return None
