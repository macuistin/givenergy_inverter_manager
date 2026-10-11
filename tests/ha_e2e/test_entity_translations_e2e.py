"""Every switch and number is named, and given its icon, by translation.

The sensors and the button were already. The five switches and four numbers that set a name in
code now use a translation key equal to their unique ID suffix. The names are in strings.json and
the icons in icons.json, which is what the entity-translations and icon-translations rules of the
quality scale ask for.
"""

from __future__ import annotations

import json

import pytest
from conftest import MIDDAY
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.icon import async_get_icons

from custom_components.givenergy_inverter_manager.const import DOMAIN
from tests.helpers import PKG


@pytest.fixture
def scenario():
    return MIDDAY


class TestEverySwitchAndNumber:
    async def test_every_switch_and_number_is_named_and_given_an_icon_by_translation(
        self, hass, loaded_entry
    ):
        """Names come from strings.json and icons from icons.json, for the old entities too.

        Home Assistant resolves an icon translation in the frontend, so the icon is read through
        the same helper the frontend's icon request uses.
        """
        strings = json.loads((PKG / "strings.json").read_text(encoding="utf-8"))["entity"]
        icons = (await async_get_icons(hass, "entity", [DOMAIN]))[DOMAIN]
        registry = er.async_get(hass)
        entries = [
            e
            for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
            if e.domain in ("switch", "number")
        ]
        assert len(entries) == 16
        for entry in entries:
            key = entry.unique_id.removeprefix(f"{loaded_entry.entry_id}_")
            assert entry.translation_key == key, key
            assert entry.original_name == strings[entry.domain][key]["name"], key
            assert icons[entry.domain][key]["default"].startswith("mdi:"), key

    async def test_no_translation_or_icon_is_left_without_an_entity(self, hass, loaded_entry):
        """A key in strings.json or icons.json with no entity behind it is a rename gone wrong."""
        strings = json.loads((PKG / "strings.json").read_text(encoding="utf-8"))["entity"]
        icons = (await async_get_icons(hass, "entity", [DOMAIN]))[DOMAIN]
        registry = er.async_get(hass)
        for domain in ("switch", "number"):
            registered = {
                e.unique_id.removeprefix(f"{loaded_entry.entry_id}_")
                for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
                if e.domain == domain
            }
            assert set(strings[domain]) == registered, domain
            assert set(icons[domain]) == registered, domain
