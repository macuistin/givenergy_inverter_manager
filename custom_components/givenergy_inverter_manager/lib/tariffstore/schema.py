"""The one definition of the stored format: validate a tariff file and a country block, and
compute the checksum. Standard library only. docs/format.md describes the format in words.

The sync scripts, the index build, the check and a client all call these functions, so nothing
can be written, indexed or priced that this module refuses.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
HOURS = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
REF = re.compile(r"^\$(country|input)\.([a-z][a-z0-9_]*)$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?$")
EXPORT_REF = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*$")

TARIFF_REQUIRED = {"schema", "name", "provider", "effective_from", "source", "bands", "areas"}
TARIFF_OPTIONAL = {"effective_to", "service", "customer_class", "timezone", "direction", "export",
                   "prices_include_tax", "bill", "inputs", "checks"}
COUNTRY_RESERVED = {"schema", "country", "currency", "timezone", "vat_percent", "bill", "inputs",
                    "availability", "reason", "holidays", "providers"}
YEAR = re.compile(r"^\d{4}$")
REGION = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
BAND_FIELDS = {"name", "hours", "days", "months", "holidays"}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# How much of a country's rates the repository holds. A country with tariff files is available or
# partial (partial says why in `reason`). A country with none is unavailable, with the reason.
AVAILABILITY = ("available", "partial", "unavailable")
NODE_FIELDS = {
    "energy_by_band": {"kind", "round_bands", "round"},
    "series_energy": {"kind", "series", "round"},
    "tiered_energy": {"kind", "blocks", "limits", "bands", "round"},
    "export_credit": {"kind", "round"},
    "per_day": {"kind", "amount", "round"},
    "per_kwh": {"kind", "amount", "on", "round"},
    "demand": {"kind", "window", "price", "per", "hours", "days", "months", "holidays", "round"},
    "per_period": {"kind", "amount", "share", "per", "round"},
    "adjust": {"kind", "name", "percent", "of", "round"},
    "tax": {"kind", "name", "percent", "mode", "of", "round"},
    "minimum": {"kind", "amount", "per", "of", "round"},
    "maximum": {"kind", "amount", "per", "of", "round"},
    "sum": {"kind", "of", "round"},
}
BLOCK_FIELDS = {"from_kwh", "upto_kwh", "price"}
MAX_DEPTH = 8
PERIOD_FIELDS = {"rule", "start_day", "months", "start_month"}
PERIOD_MONTHS = (1, 2, 3, 4, 6, 12)  # lengths that start in the same months every year
OPEN = "9999-12-31"
COUNTRY_REQUIRED = ("country", "currency", "timezone", "vat_percent", "bill")
AREA_FIELDS = {"label", "region", "standing", "rates"}
HOLIDAY_FIELDS = {"source", "years", "regions"}
Doc = dict[str, Any]


def canonical(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def checksum(doc: object) -> str:
    return "sha256:" + hashlib.sha256(canonical(doc)).hexdigest()


def stamp_ok(value: object) -> bool:
    """A date, or a UTC date and time such as 2026-11-10T08:15:00Z."""
    if not isinstance(value, str) or not STAMP.match(value):
        return False
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def _price(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not DECIMAL.match(value):
        errors.append(f"{field}: must be a decimal string")


def _number(value: object, field: str, errors: list[str]) -> None:
    """A decimal string, or a $country.name / $input.name reference."""
    if isinstance(value, str) and REF.match(value):
        return
    _price(value, field, errors)


def _date(value: object, field: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{field}: not an ISO date")


def _children(node: Doc, path: str, depth: int, errors: list[str]) -> None:
    kind = node["kind"]
    if kind in ("adjust", "tax", "minimum", "maximum"):
        _node(node.get("of"), f"{path}.of", depth + 1, errors)
    if kind != "sum":
        return
    children = node.get("of")
    if not isinstance(children, dict) or not children:
        errors.append(f"{path}.of: sum needs one or more named children")
        return
    for name, child in children.items():
        _node(child, f"{path}.of.{name}", depth + 1, errors)


def _tiers(node: Doc, path: str, errors: list[str]) -> None:
    """A tier table: named blocks that start at 0, meet end to start, and end open."""
    if node.get("limits", "period") not in ("period", "month", "day"):
        errors.append(f"{path}.limits: must be period, month or day")
    bands = node.get("bands", [])
    if not isinstance(bands, list) or any(not isinstance(b, str) for b in bands) or (
        "bands" in node and not bands
    ):
        errors.append(f"{path}.bands: must be a list of band names")
    blocks = node.get("blocks")
    if not isinstance(blocks, dict) or not blocks:
        errors.append(f"{path}.blocks: needs one or more named blocks")
        return
    rows = {n: _block(n, r, f"{path}.blocks.{n}", errors) for n, r in blocks.items()}
    ranges = [(row[0], row[1], name) for name, row in rows.items() if row is not None]
    if len(ranges) < len(rows):
        return
    expected: Decimal | None = Decimal(0)
    for start, end, name in sorted(ranges, key=lambda item: item[0]):
        if expected is None or start != expected:
            errors.append(f"{path}.blocks.{name}: must start where the block before ends, from 0")
        expected = end
    if expected is not None:
        errors.append(f"{path}.blocks: the last block needs no upto_kwh")


def _block(
    name: str, row: object, path: str, errors: list[str]
) -> tuple[Decimal, Decimal | None] | None:
    """Check one block and return its start and end, or None when it cannot be read."""
    before = len(errors)
    if not NAME.match(name) or not isinstance(row, dict) or not BLOCK_FIELDS >= set(row):
        errors.append(f"{path}: needs a name like a node and only from_kwh, upto_kwh and price")
        return None
    for key in BLOCK_FIELDS & (set(row) | {"from_kwh", "price"}):
        _price(row.get(key), f"{path}.{key}", errors)
        if str(row.get(key)).startswith("-"):
            errors.append(f"{path}.{key}: must be 0 or more")
    if len(errors) > before:
        return None
    start = Decimal(row["from_kwh"])
    end = Decimal(row["upto_kwh"]) if "upto_kwh" in row else None
    if end is not None and end <= start:
        errors.append(f"{path}.upto_kwh: must be above from_kwh")
        return None
    return start, end


def _demand(node: Doc, path: str, errors: list[str]) -> None:
    """A demand charge: a window name, a price per kW, and when the window is open."""
    if not NAME.match(str(node.get("window"))):
        errors.append(f"{path}.window: needs a name like a node")
    _price(node.get("price"), f"{path}.price", errors)
    if str(node.get("price")).startswith("-"):
        errors.append(f"{path}.price: must be 0 or more")
    if node.get("per", "month") not in ("month", "period"):
        errors.append(f"{path}.per: must be month or period")
    when = {k: v for k, v in node.items() if k in ("hours", "days", "months", "holidays")}
    _band_window({"hours": "00:00-12:00", **when}, path, errors)


def _per_rule(node: Doc, path: str, errors: list[str]) -> None:
    """`per` says what an amount is written for. A floor or cap may also be per day."""
    kind = node["kind"]
    allowed = ("period", "month", "day") if kind in ("minimum", "maximum") else ("month", "period")
    default = "period" if kind in ("minimum", "maximum") else "month"
    if node.get("per", default) not in allowed:
        errors.append(f"{path}.per: must be {', '.join(allowed[:-1])} or {allowed[-1]}")


def _kind_rules(node: Doc, path: str, errors: list[str]) -> None:
    """The rules of the kinds that have fields of their own."""
    kind = node["kind"]
    if kind == "tiered_energy":
        _tiers(node, path, errors)
    if kind == "demand":
        _demand(node, path, errors)
    else:
        _per_rule(node, path, errors)
    if kind == "tax" and node.get("mode") not in ("added", "included"):
        errors.append(f"{path}.mode: must be added or included")
    if kind == "series_energy" and not (isinstance(node.get("series"), str)
                                        and NAME.match(node["series"])):
        errors.append(f"{path}.series: must be a lower case name")
    if kind in ("per_kwh", "minimum", "maximum") and "amount" not in node:
        errors.append(f"{path}.amount: missing")
    if node.get("on", "import") not in ("import", "export"):
        errors.append(f"{path}.on: must be import or export")


def _node(node: object, path: str, depth: int, errors: list[str]) -> None:
    if depth > MAX_DEPTH:
        errors.append(f"{path}: tree too deep")
        return
    if not isinstance(node, dict) or node.get("kind") not in NODE_FIELDS:
        errors.append(f"{path}: unknown node kind")
        return
    kind = node["kind"]
    errors += [f"{path}.{key}: not allowed on {kind}" for key in node
               if key not in NODE_FIELDS[kind]]
    for key in ("amount", "percent"):
        if key in node:
            _number(node[key], f"{path}.{key}", errors)
    _kind_rules(node, path, errors)
    _children(node, path, depth, errors)


def _band_window(band: Doc, where: str, errors: list[str]) -> None:
    """When a band after the first applies: hours every time, and optionally days and months."""
    hours = str(band.get("hours"))
    if not HOURS.match(hours) or hours[:5] == hours[6:]:
        errors.append(f"{where}.hours: must be HH:MM-HH:MM with different ends")
    days = band.get("days", ["mon"])
    if not isinstance(days, list) or not days or len(set(days)) != len(days) \
            or any(d not in WEEKDAYS for d in days):
        errors.append(f"{where}.days: distinct values from {', '.join(WEEKDAYS)}")
    months = band.get("months", [1])
    if not isinstance(months, list) or not months or len(set(months)) != len(months) \
            or any(type(m) is not int or not 1 <= m <= 12 for m in months):
        errors.append(f"{where}.months: distinct month numbers from 1 to 12")
    if band.get("holidays", "weekend") != "weekend":
        errors.append(f"{where}.holidays: write it only as weekend")


def _source(source: object, errors: list[str]) -> None:
    if not isinstance(source, dict) or set(source) != {"id", "url"} \
            or not SLUG.match(str(source["id"])) or not str(source["url"]).startswith("https://"):
        errors.append("source: needs id (the name of a file in sources/) and an https url")


def _timezone(value: object, field: str, errors: list[str]) -> None:
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"{field}: not an IANA time zone")


def _period_number(value: object, allowed: Collection[int]) -> bool:
    """A whole number from `allowed`, or a reference the compile step resolves."""
    if isinstance(value, str):
        return bool(REF.match(value))
    return type(value) is int and value in allowed


def _period(period: object, errors: list[str]) -> None:
    if not isinstance(period, dict) or period.get("rule") != "monthly":
        errors.append("bill.period: rule must be monthly")
        return
    errors += [f"bill.period.{key}: not allowed" for key in period if key not in PERIOD_FIELDS]
    if not _period_number(period.get("start_day"), range(1, 29)):
        errors.append("bill.period.start_day: must be a day number from 1 to 28 or a reference")
    if not _period_number(period.get("months", 1), PERIOD_MONTHS):
        errors.append("bill.period.months: must be 1, 2, 3, 4, 6 or 12, or a reference")
    if not _period_number(period.get("start_month", 1), range(1, 13)):
        errors.append("bill.period.start_month: must be a month number or a reference")


def _bill(bill: object, errors: list[str], *, country: bool = False) -> None:
    """A country's bill needs a tree. A tariff's may give a tree, a period or both."""
    if not isinstance(bill, dict) or set(bill) - {"period", "total", "netting"} \
            or not ({"total"} if country else {"period", "total"}) & set(bill):
        errors.append("bill: needs total and optional period" if country
                      else "bill: needs total, period or both")
        return
    if bill.get("period") is not None:
        _period(bill["period"], errors)
    if bill.get("netting", "none") not in ("none", "band"):
        errors.append("bill.netting: must be none or band")
    if "total" in bill:
        _node(bill["total"], "bill.total", 0, errors)


def _inputs(inputs: object, errors: list[str]) -> None:
    if not isinstance(inputs, dict):
        errors.append("inputs: must be an object")
        return
    for name, spec in inputs.items():
        if not NAME.match(name) or not isinstance(spec, dict) or set(spec) != {
                "type", "min", "max", "default"} or spec.get("type") != "integer":
            errors.append(f"inputs.{name}: needs type integer, min, max and default")


def _header(doc: Doc, errors: list[str]) -> None:
    """The fields that say what the tariff is and where it came from."""
    if doc["schema"] != 1:
        errors.append("schema: must be 1")
    errors += [f"{key}: must be text" for key in ("name", "provider")
               if not doc[key] or not isinstance(doc[key], str)]
    _source(doc["source"], errors)
    if "service" in doc:
        errors.append("service: electricity is the default and no other service is priced yet")
    if "customer_class" in doc and doc["customer_class"] != "commercial":
        errors.append("customer_class: write it only when commercial")
    if "timezone" in doc:
        _timezone(doc["timezone"], "timezone", errors)
    if doc.get("direction", "import") not in ("import", "export"):
        errors.append("direction: must be export when present")
    if doc.get("prices_include_tax", False) is not False:
        errors.append("prices_include_tax: write it only when false")


def _dates(doc: Doc, errors: list[str]) -> None:
    _date(doc["effective_from"], "effective_from", errors)
    if doc.get("effective_to") is None:
        return
    _date(doc["effective_to"], "effective_to", errors)
    if str(doc["effective_to"]) <= str(doc["effective_from"]):
        errors.append("effective_to: must be after effective_from")


def _bands(bands: object, errors: list[str]) -> list[str]:
    """Check the bands and return their names, which every area must price."""
    names: list[str] = []
    if not isinstance(bands, list) or not bands:
        errors.append("bands: needs at least one band")
        return names
    for i, band in enumerate(bands):
        if not isinstance(band, dict) or not band.get("name") or set(band) - BAND_FIELDS:
            errors.append(f"bands[{i}]: needs name and, after the first, hours")
            continue
        names.append(band["name"])
        if i == 0 and len(band) > 1:
            errors.append("bands[0]: the first band is the base and has only a name")
        if i > 0:
            _band_window(band, f"bands[{i}]", errors)
    if len(set(names)) != len(names):
        errors.append("bands: names must be unique")
    return names


def _rates(rates: object, where: str, names: list[str], errors: list[str]) -> None:
    if not isinstance(rates, dict) or set(rates) != set(names):
        errors.append(f"{where}.rates: must price exactly the bands {names}")
        return
    for band, price in rates.items():
        _price(price, f"{where}.rates.{band}", errors)


def _area(key: object, row: object, tariff: tuple[list[str], bool], errors: list[str]) -> None:
    """One area row. `tariff` is the band names and whether the file is an export."""
    names, is_export = tariff
    where = f"areas.{key}"
    if not SLUG.match(str(key)) or not isinstance(row, dict):
        errors.append(f"{where}: key must be a slug and the row an object")
        return
    if set(row) - AREA_FIELDS:
        errors.append(f"{where}: only label, region, standing and rates are allowed")
    if key != "all" and not row.get("label"):
        errors.append(f"{where}.label: missing")
    if is_export and "standing" in row:
        errors.append(f"{where}.standing: an export has no standing charge")
    if not is_export:
        _price(row.get("standing"), f"{where}.standing", errors)
    _rates(row.get("rates"), where, names, errors)


def _areas(areas: object, tariff: tuple[list[str], bool], errors: list[str]) -> None:
    if not isinstance(areas, dict) or not areas:
        errors.append("areas: needs at least one area")
        return
    for key, row in areas.items():
        _area(key, row, tariff, errors)


def _band_refs(tree: object, path: str, names: list[str], errors: list[str]) -> None:
    """A tier table may name only bands the file has."""
    if not isinstance(tree, dict):
        return
    if tree.get("kind") == "tiered_energy" and isinstance(tree.get("bands"), list):
        errors += [f"{path}.bands: {b!r} is not a band of this tariff"
                   for b in tree["bands"] if b not in names]
    for key, child in tree.items():
        sub = f"{path}.{key}"
        if isinstance(child, dict):
            _band_refs(child, sub, names, errors)


def _extras(doc: Doc, errors: list[str], *, is_export: bool) -> None:
    """The optional parts: a bill of its own, inputs, checks and a paired export."""
    if "bill" in doc:
        _bill(doc["bill"], errors)
        if is_export:
            errors.append("bill: an export file has no bill of its own")
    if "inputs" in doc:
        _inputs(doc["inputs"], errors)
    if "checks" in doc and not isinstance(doc["checks"], dict):
        errors.append("checks: must be an object")
    if "export" in doc and (is_export or not EXPORT_REF.match(str(doc["export"]))):
        errors.append("export: an import file may name one export file as provider-id/tariff-id")


def validate_tariff(doc: object) -> list[str]:
    """Refusals for a tariff file, each naming the field. Empty means valid."""
    if not isinstance(doc, dict):
        return ["document: must be an object"]
    errors = [f"{key}: missing" for key in TARIFF_REQUIRED - doc.keys()]
    errors += [f"{key}: not allowed" for key in doc.keys() - TARIFF_REQUIRED - TARIFF_OPTIONAL]
    if errors:
        return sorted(errors)
    is_export = doc.get("direction") == "export"
    _header(doc, errors)
    _dates(doc, errors)
    names = _bands(doc["bands"], errors)
    _band_refs(doc.get("bill"), "bill", names, errors)
    _areas(doc["areas"], (names, is_export), errors)
    _extras(doc, errors, is_export=is_export)
    return sorted(errors)


def _vat(vat: object, errors: list[str]) -> None:
    """One rate, or a list of rates with the dates each applies."""
    if not isinstance(vat, list):
        _price(vat, "vat_percent", errors)
        return
    for i, entry in enumerate(vat):
        dated = entry if isinstance(entry, dict) else {}
        _price(dated.get("percent"), f"vat_percent[{i}].percent", errors)
        for key in ("effective_from", "effective_to"):
            if key in dated:
                _date(dated[key], f"vat_percent[{i}].{key}", errors)


def _availability(block: Doc, errors: list[str]) -> None:
    availability = block.get("availability", "available")
    if availability not in ("available", "partial"):
        errors.append("availability: a country with tariff files is available or partial")
    reason = block.get("reason")
    if availability == "partial" and not (isinstance(reason, str) and reason.strip()):
        errors.append("reason: a partial country says what is missing")


def _day_in(day: object, year: str) -> bool:
    return isinstance(day, str) and len(day) == 10 and stamp_ok(day) and day.startswith(year)


def _holiday_years(years: object, where: str, errors: list[str]) -> None:
    """One list of dates for each year held. A year that is missing is not known, never empty."""
    if not isinstance(years, dict) or not years:
        errors.append(f"{where}: must be an object of year to dates")
        return
    for year, days in years.items():
        if not (YEAR.match(str(year)) and isinstance(days, list) and days):
            errors.append(f"{where}.{year}: must be a year with a list of dates")
        elif not all(_day_in(day, str(year)) for day in days):
            errors.append(f"{where}.{year}: every entry must be a date in {year}")
        elif days != sorted(set(days)):
            errors.append(f"{where}.{year}: dates must be in order with none repeated")


def _holidays(block: Doc, errors: list[str]) -> None:
    """The public holidays a band with `"holidays": "weekend"` is priced by."""
    held = block["holidays"]
    if not isinstance(held, dict) or not {"source", "years"} <= set(held) <= HOLIDAY_FIELDS:
        errors.append("holidays: needs source and years, and may have regions")
        return
    if not str(held["source"]).startswith("https://"):
        errors.append("holidays.source: must be the https address the dates are published at")
    _holiday_years(held["years"], "holidays.years", errors)
    regions = held.get("regions", {})
    if not isinstance(regions, dict):
        errors.append("holidays.regions: must be an object of region to years")
        return
    for code, years in regions.items():
        if not (REGION.match(str(code)) and str(code).startswith(f"{block['country']}-")):
            errors.append(f"holidays.regions.{code}: must be an ISO 3166-2 code of this country")
        _holiday_years(years, f"holidays.regions.{code}", errors)


def validate_country(block: object) -> list[str]:
    """Refusals for the hand-maintained top block of a country index."""
    if not isinstance(block, dict):
        return ["country block: must be an object"]
    errors = [f"{key}: missing" for key in COUNTRY_REQUIRED if key not in block]
    if errors:
        return errors
    if not re.match(r"^[A-Z]{2}$", str(block["country"])):
        errors.append("country: must be an ISO 3166-1 alpha-2 code")
    if not re.match(r"^[A-Z]{3}$", str(block["currency"])):
        errors.append("currency: must be an ISO 4217 code")
    _timezone(block["timezone"], "timezone", errors)
    _vat(block["vat_percent"], errors)
    for key in block.keys() - COUNTRY_RESERVED:
        _price(block[key], key, errors)
    _bill(block["bill"], errors, country=True)
    if "inputs" in block:
        _inputs(block["inputs"], errors)
    _availability(block, errors)
    if "holidays" in block:
        _holidays(block, errors)
    return errors


def validate_unavailable(doc: object) -> list[str]:
    """Refusals for tariffs/unavailable.json: countries we looked at and cannot hold rates for."""
    errors: list[str] = []
    if not isinstance(doc, dict) or set(doc) != {"schema", "countries"} or doc.get("schema") != 1:
        return ["unavailable: needs schema 1 and countries"]
    for code, entry in doc["countries"].items():
        where = f"unavailable.{code}"
        if not re.match(r"^[A-Z]{2}$", str(code)):
            errors.append(f"{where}: key must be an ISO 3166-1 alpha-2 code")
        if not isinstance(entry, dict) or set(entry) != {"reason", "checked"}:
            errors.append(f"{where}: needs reason and checked")
            continue
        if not (isinstance(entry["reason"], str) and entry["reason"].strip()):
            errors.append(f"{where}.reason: say why")
        if not stamp_ok(entry["checked"]):
            errors.append(f"{where}.checked: not a date")
    return errors


def vat_on(block: Doc, on: str) -> str | None:
    """The VAT rate in force on an ISO date, or None when no entry covers it.

    Later entries win, so an undated first entry is the fallback and a dated entry after it is a
    temporary change that ends and hands back to the fallback."""
    vat = block["vat_percent"]
    if not isinstance(vat, list):
        return str(vat)
    found: str | None = None
    for entry in vat:
        if entry.get("effective_from", "0000-01-01") <= on < entry.get("effective_to", OPEN):
            found = entry["percent"]
    return found


def holiday_years(block: Doc, region: str | None = None) -> dict[int, frozenset[str]] | None:
    """{year: ISO dates} of the public holidays a country block holds, or None when it holds none.

    A region that has its own list uses it whole. Any other region has the country's list."""
    held = block.get("holidays")
    if held is None:
        return None
    years = held.get("regions", {}).get(region, held["years"])
    return {int(year): frozenset(days) for year, days in years.items()}
