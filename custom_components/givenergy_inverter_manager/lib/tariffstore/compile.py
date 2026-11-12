"""Build the full definition the bill engine (lib/tariff) reads, from a tariff file and its
country block. Standard library only.

The tariff file has bands and one row of rates per area. The country block has the currency, the
time zone, the VAT rate and the standard bill. `$country.name` takes a value from the country block
and `$input.name` becomes a reference to a customer input. Nothing here changes a price.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from typing import Any

from .schema import REF, Doc, vat_on


class CompileError(ValueError):
    pass


def _country_value(match: re.Match[str], block: Doc, on: str, path: str) -> Any:
    if match.group(1) != "country":
        raise CompileError(f"{path}: $input is only allowed in the bill period")
    name = match.group(2)
    value = vat_on(block, on) if name == "vat_percent" else block.get(name)
    if value is None or isinstance(value, (dict, list)):
        raise CompileError(f"{path}: country has no value for {name} on {on}")
    return value


def _resolve(node: Any, block: Doc, on: str, path: str = "") -> Any:
    """Copy of a bill tree with `$country.x` replaced by its value."""
    if isinstance(node, dict):
        return {k: _resolve(v, block, on, f"{path}.{k}") for k, v in node.items()}
    match = REF.match(node) if isinstance(node, str) else None
    return _country_value(match, block, on, path) if match else node


def _nodes(node: Doc) -> Iterator[Doc]:
    yield node
    child = node.get("of")
    if isinstance(child, dict):
        if "kind" in child:
            yield from _nodes(child)
        else:
            for sub in child.values():
                yield from _nodes(sub)


def _add_export_credit(total: Doc) -> None:
    """Add an export_credit line to the outermost sum, so a paired export price is paid."""
    node = total
    while node["kind"] != "sum":
        if "of" not in node or "kind" not in node["of"]:
            raise CompileError("no sum in the bill to add an export credit to")
        node = node["of"]
    node["of"].setdefault("export", {"kind": "export_credit"})


def _zone(band: Doc, priority: int, price: str) -> Doc:
    zone = {"name": band["name"], "priority": priority, "hours": band["hours"], "price": price}
    zone.update({k: band[k] for k in ("days", "months", "holidays") if k in band})
    return zone


def _prices(bands: list[Doc], rates: dict[str, str]) -> Doc:
    """The engine's price table: the first band is the base, each later band a zone that wins
    over the ones before it."""
    base = {"name": bands[0]["name"], "price": rates[bands[0]["name"]]}
    zones = [_zone(band, i, rates[band["name"]]) for i, band in enumerate(bands[1:], 1)]
    return {"base": base, "zones": zones}


def export_prices(export_file: Doc, area: str = "all") -> Doc:
    """The export prices for `area`, flat or by time of day. An export file with no row for the
    area pays its first row, which is how a single national export price is written."""
    areas = export_file["areas"]
    row = areas.get(area) or next(iter(areas.values()))
    prices = _prices(export_file["bands"], row["rates"])
    return prices if prices["zones"] else {"base": prices["base"]}


def _period(bill: Doc, block: Doc, inputs: Doc) -> Doc:
    """The bill period, with each `$input.name` turned into the engine's input reference.

    A tariff's own period replaces the country's whole period, so the two are never mixed."""
    period: Doc = bill.get("period") or copy.deepcopy(block["bill"]["period"])
    for key in ("start_day", "months", "start_month"):
        value = period.get(key)
        if isinstance(value, str):
            match = REF.match(value)
            if not match or match.group(1) != "input" or match.group(2) not in inputs:
                raise CompileError(f"bill.period.{key}: {value} is not a declared input")
            period[key] = {"input": match.group(2)}
    return period


def _total(bill: Doc, block: Doc, on: str, standing: object) -> Doc:
    """The bill tree with country values filled in and the area's standing charge on each day."""
    total: Doc = _resolve(bill["total"], block, on)
    for node in _nodes(total):
        if node.get("kind") == "per_day" and node.get("amount") is None:
            node["amount"] = standing
    return total


def compile_area(tariff: Doc, area: str, *, block: Doc, meta: Doc,  # noqa: PLR0913
                 on: str, export_file: Doc | None = None) -> Doc:
    """The engine's definition for one area of a tariff, priced on the ISO date `on`.

    `meta` is what the path says: country, provider id, tariff id and revision number."""
    if area not in tariff["areas"]:
        raise CompileError(f"no area {area}; this tariff has {', '.join(tariff['areas'])}")
    row = tariff["areas"][area]
    bill = copy.deepcopy({**block["bill"], **tariff.get("bill", {})})
    inputs = {**copy.deepcopy(block.get("inputs", {})), **tariff.get("inputs", {})}
    period = _period(bill, block, inputs)
    total = _total(bill, block, on, row["standing"])
    export: Doc = {"base": {"name": "Export", "price": "0"}}
    if export_file is not None:
        _add_export_credit(total)
        export = export_prices(export_file, area)
    revision = int(meta["revision"])
    return {
        "schema": 1,
        "id": meta["tariff"] if area == "all" else f"{meta['tariff']}-{area}",
        "revision": revision, "supersedes": revision - 1 or None,
        "name": tariff["name"] if area == "all" else f"{tariff['name']} ({row['label']})",
        "service": tariff.get("service", "electricity"),
        "customer_class": tariff.get("customer_class", "residential"),
        "provider": {"id": meta["provider"], "name": tariff["provider"]},
        "country": meta["country"], "region": None,
        "currency": block["currency"], "timezone": tariff.get("timezone", block["timezone"]),
        "effective_from": tariff["effective_from"], "effective_to": meta.get("effective_to"),
        "source_url": tariff["source"]["url"], "last_verified": None,
        "completeness": "complete" if tariff.get("checks") else "partial",
        "inputs": inputs, "import": _prices(tariff["bands"], row["rates"]), "export": export,
        "bill": {"period": period, "total": total}, "checks": tariff.get("checks", {}),
    }


def check_references(tariff: Doc, block: Doc) -> list[str]:
    """Every `$country.x` the tariff or the country bill uses must exist in the country block."""
    problems = []
    for where, tree in (("tariff", tariff.get("bill")), ("country bill", block["bill"])):
        for ref in re.findall(r"\$country\.([a-z][a-z0-9_]*)", json.dumps(tree or {})):
            if ref not in block:
                problems.append(f"{where}: $country.{ref} is not in the country block")
    return problems
