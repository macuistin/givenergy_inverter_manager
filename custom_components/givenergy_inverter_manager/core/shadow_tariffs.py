"""
shadow_tariffs.py - the tariffs priced beside the active one, as the options store them.

A shadow tariff is a name and the rate fields a user changes when comparing offers: the rates,
the timed rates, the standing charge, the levy, VAT and the discount. The base rate name and the
bill start day follow the active tariff, so every shadow is priced over the same bill period and
the comparison is like for like. A shadow only re-prices measured energy. Nothing here reaches
the write path.

Everything works on plain values. This module imports only the option keys and the limit, so no
chain of imports from it can reach the inverter (tests/test_shadow_cannot_write.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..conf import (
    CONF_BASE_RATE,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_INCLUDED,
    CONF_VAT_RATE,
)
from ..tuning import MAX_SHADOW_TARIFFS

KEY_NAME = "name"
KEY_SOURCE = "source"  # where a shadow chosen from the store came from, for the settings page

# The fields a shadow tariff sets itself. Anything else comes from the active tariff.
SHADOW_FIELDS: tuple[str, ...] = (
    CONF_BASE_RATE,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_PSO_LEVY,
    CONF_VAT_RATE,
    CONF_DISCOUNT_RATE,
)

# Set only when the user picked the tariff from the store. A tariff typed by hand has neither, and
# then takes VAT as the active tariff does.
SHADOW_OPTIONAL: tuple[str, ...] = (CONF_VAT_INCLUDED, KEY_SOURCE)


def shadow_entries(raw: Any) -> list[dict[str, Any]]:
    """The saved shadow tariffs: those with a name and every field, at most the limit.

    An unreadable entry is skipped, so a hand-edited option never stops the integration.
    """
    if not isinstance(raw, list):
        return []
    entries = [dict(item) for item in raw if _readable(item)]
    return entries[:MAX_SHADOW_TARIFFS]


def _readable(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and bool(str(item.get(KEY_NAME) or "").strip())
        and all(key in item for key in SHADOW_FIELDS)
    )


def shadow_names(raw: Any) -> list[str]:
    return [str(entry[KEY_NAME]) for entry in shadow_entries(raw)]


def name_error(raw: Any, name: str) -> str | None:
    """The form error for adding a shadow tariff called *name*, or None when it can be added."""
    entries = shadow_entries(raw)
    if len(entries) >= MAX_SHADOW_TARIFFS:
        return "shadow_limit"
    wanted = name.strip().casefold()
    if not wanted:
        return "shadow_name_missing"
    if wanted in (entry[KEY_NAME].strip().casefold() for entry in entries):
        return "shadow_name_duplicate"
    return None


def with_shadow(raw: Any, entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The list with *entry* added. Raises ValueError for a bad name or a full list."""
    error = name_error(raw, str(entry.get(KEY_NAME) or ""))
    if error:
        raise ValueError(error)
    stored = {
        KEY_NAME: str(entry[KEY_NAME]).strip(),
        **{k: entry[k] for k in SHADOW_FIELDS},
        **{k: entry[k] for k in SHADOW_OPTIONAL if k in entry},
    }
    return [*shadow_entries(raw), stored]


def without_shadow(raw: Any, name: str) -> list[dict[str, Any]]:
    """The list without the tariff called *name*. An unknown name leaves it as it is."""
    return [entry for entry in shadow_entries(raw) if entry[KEY_NAME] != name]


def shadow_config(entry: Mapping[str, Any], active: Mapping[str, Any]) -> dict[str, Any]:
    """The config that builds the shadow's tariff: the active config under the shadow's fields."""
    own = (*SHADOW_FIELDS, CONF_VAT_INCLUDED)
    return {**active, **{key: entry[key] for key in own if key in entry}}


def shadow_summary(raw: Any) -> str:
    """One line for the menu: how many shadow tariffs there are and their names."""
    names = shadow_names(raw)
    if not names:
        return "None set up"
    return f"{len(names)} of {MAX_SHADOW_TARIFFS}: {', '.join(names)}"


def unique_shadow_name(raw: Any, wanted: str) -> str:
    """*wanted*, or "wanted (2)" and on, when a shadow tariff already has that name."""
    taken = {entry[KEY_NAME].strip().casefold() for entry in shadow_entries(raw)}
    name, number = wanted.strip(), 2
    while name.casefold() in taken:
        name = f"{wanted.strip()} ({number})"
        number += 1
    return name


def shadow_entry_from_options(name: str, options: Mapping[str, Any]) -> dict[str, Any]:
    """A shadow tariff from the options a store plan was copied into, with where it came from."""
    record = options["tariff_source"]
    source = {
        key: record[key]
        for key in ("country", "provider", "tariff", "area", "effective_from")
        if key in record
    }
    return {
        KEY_NAME: name,
        **{key: options[key] for key in SHADOW_FIELDS},
        CONF_VAT_INCLUDED: bool(options.get(CONF_VAT_INCLUDED, False)),
        KEY_SOURCE: source,
    }
