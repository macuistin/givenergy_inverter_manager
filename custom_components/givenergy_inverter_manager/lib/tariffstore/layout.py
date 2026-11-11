"""How the JSON files are written: single values first, the collection last, two-space indent.

One writer for every file, so a rebuild of unchanged data changes no byte. The order never changes
a checksum, which sorts keys itself.
"""
from __future__ import annotations

import json
from typing import Any

INDEX_FIRST = ("schema", "country", "currency", "timezone", "vat_percent", "availability", "reason",
               "inputs", "bill", "holidays")
TARIFF_FIRST = ("schema", "name", "provider", "service", "customer_class", "direction", "timezone",
                "effective_from", "effective_to", "source", "prices_include_tax", "export")
TARIFF_LAST = ("bands", "areas")


def _sorted(value: object) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def dumps(doc: dict[str, Any], first: tuple[str, ...] = (), last: tuple[str, ...] = ()) -> str:
    head = [k for k in first if k in doc]
    tail = [k for k in last if k in doc]
    middle = sorted(k for k in doc if k not in head and k not in tail)
    return json.dumps({k: _sorted(doc[k]) for k in head + middle + tail}, indent=2,
                      ensure_ascii=False) + "\n"


def dumps_index(doc: dict[str, Any]) -> str:
    return dumps(doc, first=INDEX_FIRST, last=("providers",))


def dumps_root(doc: dict[str, Any]) -> str:
    return dumps(doc, first=("schema",), last=("countries",))


def dumps_tariff(doc: dict[str, Any]) -> str:
    return dumps(doc, first=TARIFF_FIRST, last=TARIFF_LAST)
