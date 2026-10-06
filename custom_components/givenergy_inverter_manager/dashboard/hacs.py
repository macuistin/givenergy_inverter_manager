"""
hacs.py - the custom cards from HACS, and the fallbacks used when they are not installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ..logging import get_logger

_LOG = get_logger(__name__)


# ── HACS cards ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HacsCard:
    """A custom card from HACS, with the note the generated file carries about it."""

    name: str
    url: str
    header: str

    @property
    def card_type(self) -> str:
        return f"custom:{self.name}"

    @property
    def note(self) -> str:
        return f"{self.name}: {self.url}"


POWER_FLOW_CARD = HacsCard(
    "power-flow-card-plus",
    "https://github.com/flixlix/power-flow-card-plus",
    "# The live power flow requires power-flow-card-plus from HACS:\n"
    "#   https://github.com/flixlix/power-flow-card-plus\n",
)
APEX_CARD = HacsCard(
    "apexcharts-card",
    "https://github.com/RomRider/apexcharts-card",
    "# The immersion charts require apexcharts-card from HACS:\n"
    "#   https://github.com/RomRider/apexcharts-card\n",
)
HACS_CARDS = (POWER_FLOW_CARD, APEX_CARD)


class HacsCards:
    """Decides between each HACS card and its built-in fallback, once, and remembers why.

    The header comment of the generated file reads the outcome: which custom cards the
    dashboard uses and which fallbacks stand in for cards that are not installed.
    """

    def __init__(self, resources: list[str] | None) -> None:
        self._resources = resources
        self.used: set[HacsCard] = set()
        self.fallbacks: list[HacsCard] = []

    def use(self, card: HacsCard) -> bool:
        """True to build the HACS card. False means build the built-in fallback instead."""
        if self._installed(card):
            self.used.add(card)
            return True
        if card not in self.fallbacks:
            self.fallbacks.append(card)
        return False

    def _installed(self, card: HacsCard) -> bool:
        """True unless the Lovelace resources are known and do not include this card.

        Unknown resources (None) mean the generator could not read them, in which
        case the custom card is assumed to be there, as it always was.
        """
        if self._resources is None:
            return True
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
