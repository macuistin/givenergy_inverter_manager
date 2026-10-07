"""Entity IDs, unique ID keys and display names must not drift between releases."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.helpers import entity_registry as er

_SNAPSHOT = Path(__file__).with_name("entity_snapshot.json")


async def test_entity_ids_keys_and_names_match_the_recorded_snapshot(
    hass, loaded_entry_with_charger
):
    """The full install: every optional device present, so every entity exists."""
    loaded_entry = loaded_entry_with_charger
    registry = er.async_get(hass)
    prefix = f"{loaded_entry.entry_id}_"
    actual = sorted(
        (
            {
                "entity_id": e.entity_id,
                "key": e.unique_id.removeprefix(prefix),
                "name": e.original_name,
            }
            for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        ),
        key=lambda row: row["entity_id"],
    )
    expected = sorted(json.loads(_SNAPSHOT.read_text("utf-8")), key=lambda row: row["entity_id"])

    assert actual == expected
