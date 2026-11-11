"""definition_parse.py: read a tariff document and refuse anything that is not understood.

The document is JSON. A bad document raises DefinitionError naming the field, and nothing is
repaired or guessed: an unknown key, an unknown node kind, a number where a decimal string is
required, a date that is not YYYY-MM-DD and a reference to something undeclared are all refused.

Shape, top level (every key is required unless marked optional):

    schema, id, revision, supersedes (null or an earlier revision), name, service, customer_class,
    provider {id, name}, country, region (null or ISO 3166-2), currency, timezone,
    effective_from, effective_to (null), source_url (null), last_verified (null), completeness,
    inputs {name: {type, min, max, default}}, import {base, zones}, export {base, zones?},
    bill {period {rule, start_day}, total <node>}, checks {name: {...}} (optional)

The bill tree and the vocabulary of node kinds are described in definition.py. Prices, amounts,
percentages and kWh are strings such as "0.365", so no float ever stands for money. A JSON number
with a decimal point is refused for that reason.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import date, time
from decimal import Decimal
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .defaults import MAX_TARIFF_TREE_DEPTH
from .definition import (
    SCHEMA_VERSION,
    Adjust,
    Band,
    Check,
    DefinitionError,
    EnergyByBand,
    ExportCredit,
    ExportPrices,
    ImportPrices,
    InputSpec,
    Node,
    NodeRounding,
    PerDay,
    PeriodRule,
    PerPeriod,
    Provider,
    StartDay,
    Sum,
    TariffDefinition,
    Tax,
    TaxMode,
    Zone,
)

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NODE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_HOURS = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-3]):([0-5][0-9])$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
_REGION = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_SERVICES = ("electricity",)  # others (gas) are added with their own nodes
_CUSTOMER_CLASSES = ("residential", "commercial")
_PERIOD_RULES = ("monthly",)
_SHARES = ("days_in_period", "whole")
_START_DAYS = (1, 28)  # a month always has these days

# ISO 4217 minor units that are not two places. Any other currency is taken as two.
_MINOR_UNIT_PLACES = {
    "JPY": 0, "KRW": 0, "ISK": 0, "CLP": 0, "BHD": 3, "KWD": 3, "OMR": 3, "TND": 3,
}


def load_json(text: str) -> Any:
    """Decode JSON text, refusing a number with a decimal point, NaN and Infinity.

    Raises DefinitionError. Shared by every reader of the tariff documents.
    """
    try:
        return json.loads(text, parse_float=_refuse_float, parse_constant=_refuse_constant)
    except json.JSONDecodeError as err:
        raise DefinitionError("", f"not valid JSON ({err.msg} at position {err.pos})") from err


def load_definition(text: str) -> TariffDefinition:
    """Parse JSON text into a definition. Raises DefinitionError for anything not valid."""
    return parse_definition(load_json(text))


def parse_definition(data: object) -> TariffDefinition:
    """Validate a decoded document and return it as a TariffDefinition."""
    doc = Fields(data, "")
    doc.only(
        required=(
            "schema", "id", "revision", "supersedes", "name", "service", "customer_class",
            "provider", "country", "region", "currency", "timezone", "effective_from",
            "effective_to", "source_url", "last_verified", "completeness", "inputs", "import",
            "export", "bill",
        ),
        optional=("checks",),
    )
    doc.whole("schema", SCHEMA_VERSION, SCHEMA_VERSION)  # refuses any other version
    identity = _identity(doc)
    inputs = _inputs(doc.child("inputs"))
    import_prices, export_prices = _prices(doc)
    period, total = _bill(doc.child("bill"), inputs)
    checks = _checks(doc, import_prices, export_prices)
    complete = doc.choice("completeness", ("complete", "partial")) == "complete"
    if complete and not checks:
        raise DefinitionError("completeness", "complete needs at least one entry in checks")
    zone_name = doc.text("timezone")
    return TariffDefinition(
        **identity,
        complete=complete,
        inputs=inputs,
        import_prices=import_prices,
        export_prices=export_prices,
        period=period,
        rounding_places=_MINOR_UNIT_PLACES.get(identity["currency"], 2),
        total=total,
        checks=checks,
        timezone=_zone(zone_name, "timezone"),
        timezone_name=zone_name,
    )


def _refuse_float(text: str) -> Any:
    raise DefinitionError("", f"the number {text} has a decimal point. Write money as a string")


def _refuse_constant(text: str) -> Any:
    raise DefinitionError("", f"{text} is not allowed")


class Fields:
    """One JSON object and the path to it, with typed reads that refuse the wrong type."""

    def __init__(self, data: object, path: str) -> None:
        if not isinstance(data, Mapping):
            raise DefinitionError(path, "must be an object")
        self._data: Mapping[str, Any] = data
        self.path = path

    def at(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def only(self, required: Iterable[str], optional: Iterable[str] = ()) -> None:
        required, optional = tuple(required), tuple(optional)
        for key in required:
            if key not in self._data:
                raise DefinitionError(self.at(key), "is missing")
        for key in self._data:
            if key not in (*required, *optional):
                raise DefinitionError(self.at(str(key)), "is not a known field")

    def raw(self, key: str) -> Any:
        return self._data[key]

    def has(self, key: str) -> bool:
        return key in self._data

    def child(self, key: str) -> Fields:
        return Fields(self._data[key], self.at(key))

    def items(self) -> Iterable[tuple[str, Any]]:
        return self._data.items()

    def text(self, key: str) -> str:
        value = self._data[key]
        if not isinstance(value, str) or not value.strip():
            raise DefinitionError(self.at(key), "must be a non-empty string")
        return value

    def optional_text(self, key: str) -> str | None:
        return None if self._data[key] is None else self.text(key)

    def match(self, key: str, pattern: re.Pattern[str], what: str) -> str:
        value = self.text(key)
        if not pattern.match(value):
            raise DefinitionError(self.at(key), f"must be {what}")
        return value

    def choice(self, key: str, options: Collection[str]) -> str:
        value = self.text(key)
        if value not in options:
            raise DefinitionError(self.at(key), f"must be one of {', '.join(options)}")
        return value

    def whole(self, key: str, minimum: int, maximum: int) -> int:
        return _whole(self._data[key], self.at(key), minimum, maximum)

    def money(self, key: str) -> Decimal:
        value = self.signed(key)
        if value < 0:
            raise DefinitionError(self.at(key), "must be 0 or more")
        return value

    def signed(self, key: str) -> Decimal:
        return _decimal(self._data[key], self.at(key))

    def day(self, key: str) -> date:
        return _day(self._data[key], self.at(key))

    def optional_day(self, key: str) -> date | None:
        return None if self._data[key] is None else self.day(key)

    def sequence(self, key: str) -> list[Any]:
        value = self._data[key]
        if not isinstance(value, list):
            raise DefinitionError(self.at(key), "must be a list")
        return value


def _whole(value: object, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DefinitionError(path, "must be a whole number")
    if not minimum <= value <= maximum:
        raise DefinitionError(path, f"must be {minimum} to {maximum}")
    return value


def _decimal(value: object, path: str) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.match(value):
        raise DefinitionError(path, 'must be a decimal string such as "0.365"')
    return Decimal(value)


def _day(value: object, path: str) -> date:
    if not isinstance(value, str) or not _DATE.match(value):
        raise DefinitionError(path, "must be a date written YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise DefinitionError(path, "is not a real date") from err


def _zone(name: str, path: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as err:
        raise DefinitionError(path, f"{name!r} is not a time zone") from err


def _identity(doc: Fields) -> dict[str, Any]:
    """The fields that say what the tariff is, who sells it and when it applies."""
    revision = doc.whole("revision", 1, 1_000_000)
    effective_from, effective_to = doc.day("effective_from"), doc.optional_day("effective_to")
    if effective_to is not None and effective_to <= effective_from:
        raise DefinitionError("effective_to", "must be after effective_from")
    country = doc.match("country", COUNTRY, "a two letter ISO 3166-1 code such as IE")
    return {
        "id": doc.match("id", SLUG, "lowercase letters, digits and hyphens"),
        "revision": revision,
        "supersedes": _supersedes(doc, revision),
        "name": doc.text("name"),
        "service": doc.choice("service", _SERVICES),
        "customer_class": doc.choice("customer_class", _CUSTOMER_CLASSES),
        "provider": _provider(doc.child("provider")),
        "country": country,
        "region": _region(doc, country),
        "currency": doc.match("currency", _CURRENCY, "a three letter ISO 4217 code such as EUR"),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source_url": _source_url(doc),
        "last_verified": doc.optional_day("last_verified"),
    }


def _supersedes(doc: Fields, revision: int) -> int | None:
    if doc.raw("supersedes") is None:
        return None
    earlier = doc.whole("supersedes", 1, 1_000_000)
    if earlier >= revision:
        raise DefinitionError("supersedes", "must be an earlier revision than this one")
    return earlier


def _provider(fields: Fields) -> Provider:
    fields.only(required=("id", "name"))
    return Provider(
        fields.match("id", SLUG, "lowercase letters, digits and hyphens"), fields.text("name")
    )


def _region(doc: Fields, country: str) -> str | None:
    if doc.raw("region") is None:
        return None
    region = doc.match("region", _REGION, "an ISO 3166-2 code such as GB-SCT")
    if not region.startswith(f"{country}-"):
        raise DefinitionError("region", f"must belong to the country {country}")
    return region


def _source_url(doc: Fields) -> str | None:
    url = doc.optional_text("source_url")
    if url is not None and not url.startswith(("https://", "http://")):
        raise DefinitionError("source_url", "must start with https:// or http://")
    return url


def _inputs(fields: Fields) -> dict[str, InputSpec]:
    specs: dict[str, InputSpec] = {}
    for name, _ in fields.items():
        if not _NODE_NAME.match(name):
            raise DefinitionError(fields.at(name), "is not a valid input name")
        specs[name] = _input_spec(fields.child(name))
    return specs


def _input_spec(fields: Fields) -> InputSpec:
    fields.only(required=("type", "min", "max", "default"))
    fields.choice("type", ("integer",))
    low = fields.whole("min", -1_000_000, 1_000_000)
    high = fields.whole("max", -1_000_000, 1_000_000)
    if low > high:
        raise DefinitionError(fields.at("min"), "must not be above max")
    return InputSpec(low, high, fields.whole("default", low, high))


def _prices(doc: Fields) -> tuple[ImportPrices, ExportPrices]:
    imported = doc.child("import")
    imported.only(required=("base", "zones"))
    zones = _zones(imported)
    exported = doc.child("export")
    exported.only(required=("base",), optional=("zones",))
    export_zones = _zones(exported) if exported.has("zones") else ()
    return (
        ImportPrices(_base(imported, zones), zones),
        ExportPrices(_base(exported, export_zones), export_zones),
    )


def _zones(prices: Fields) -> tuple[Zone, ...]:
    zones = tuple(_zone_of(item) for item in _zone_fields(prices))
    _unique(zones, prices, "name")
    _unique(zones, prices, "priority")
    return zones


def _base(prices: Fields, zones: tuple[Zone, ...]) -> Band:
    base = _band(prices.child("base"))
    if any(zone.name == base.name for zone in zones):
        raise DefinitionError(prices.at("zones"), f"a zone is named {base.name!r}, like the base")
    return base


def _zone_fields(imported: Fields) -> list[Fields]:
    return [
        Fields(item, f"{imported.at('zones')}[{index}]")
        for index, item in enumerate(imported.sequence("zones"))
    ]


def _unique(zones: tuple[Zone, ...], imported: Fields, attribute: str) -> None:
    seen = [getattr(zone, attribute) for zone in zones]
    if len(set(seen)) != len(seen):
        raise DefinitionError(imported.at("zones"), f"each zone needs its own {attribute}")


def _band(fields: Fields) -> Band:
    fields.only(required=("name", "price"))
    return Band(fields.text("name"), fields.money("price"))


def _zone_of(fields: Fields) -> Zone:
    fields.only(
        required=("name", "priority", "price", "hours"), optional=("days", "months", "holidays")
    )
    match = _HOURS.match(fields.text("hours"))
    if match is None:
        raise DefinitionError(fields.at("hours"), 'must be HH:MM-HH:MM such as "23:00-08:00"')
    start = time(int(match.group(1)), int(match.group(2)))
    end = time(int(match.group(3)), int(match.group(4)))
    if start == end:
        raise DefinitionError(fields.at("hours"), "must not start and end at the same time")
    return Zone(
        name=fields.text("name"),
        priority=fields.whole("priority", 1, 1000),
        price=fields.money("price"),
        start=start,
        end=end,
        days=_days(fields),
        months=_months(fields),
        holidays_as_weekend=_holidays(fields),
    )


def _days(fields: Fields) -> frozenset[int]:
    if not fields.has("days"):
        return frozenset()
    names = fields.sequence("days")
    bad = [n for n in names if n not in _WEEKDAYS]
    if bad or len(set(names)) != len(names):
        raise DefinitionError(fields.at("days"), f"must be distinct values from {_WEEKDAYS}")
    return frozenset(_WEEKDAYS.index(n) for n in names)


def _months(fields: Fields) -> frozenset[int]:
    if not fields.has("months"):
        return frozenset()
    path = fields.at("months")
    months = [_whole(m, path, 1, 12) for m in fields.sequence("months")]
    if len(set(months)) != len(months):
        raise DefinitionError(path, "must not repeat a month")
    return frozenset(months)


def _holidays(fields: Fields) -> bool:
    return fields.has("holidays") and fields.choice("holidays", ("weekend", "normal")) == "weekend"


def _bill(fields: Fields, inputs: Mapping[str, InputSpec]) -> tuple[PeriodRule, Node]:
    fields.only(required=("period", "total"))
    period = _period(fields.child("period"), inputs)
    return period, _node(fields.child("total"), 1)


def _period(fields: Fields, inputs: Mapping[str, InputSpec]) -> PeriodRule:
    fields.only(required=("rule", "start_day"))
    rule = fields.choice("rule", _PERIOD_RULES)
    path = fields.at("start_day")
    value = fields.raw("start_day")
    if isinstance(value, Mapping):
        return PeriodRule(rule, _start_day_input(fields.child("start_day"), inputs))
    return PeriodRule(rule, StartDay(_whole(value, path, *_START_DAYS), None))


def _start_day_input(fields: Fields, inputs: Mapping[str, InputSpec]) -> StartDay:
    fields.only(required=("input",))
    name = fields.text("input")
    spec = inputs.get(name)
    if spec is None:
        raise DefinitionError(fields.at("input"), f"{name!r} is not declared in inputs")
    low, high = _START_DAYS
    if spec.minimum < low or spec.maximum > high:
        raise DefinitionError(fields.at("input"), f"{name!r} must stay within {low} to {high}")
    return StartDay(None, name)


# The bill tree. Each parser reads one node kind and refuses any field it does not own.


def _rounding(fields: Fields) -> NodeRounding:
    if not fields.has("round"):
        return NodeRounding.MINOR_UNIT
    return NodeRounding(fields.choice("round", [m.value for m in NodeRounding]))


def _node(fields: Fields, depth: int) -> Node:
    if depth > MAX_TARIFF_TREE_DEPTH:
        raise DefinitionError(fields.path, f"is nested deeper than {MAX_TARIFF_TREE_DEPTH}")
    if not fields.has("kind"):
        raise DefinitionError(fields.at("kind"), "is missing")
    kind = fields.text("kind")
    parser = _NODE_PARSERS.get(kind)
    if parser is None:
        raise DefinitionError(fields.at("kind"), f"{kind!r} is not a known kind")
    return parser(fields, depth)


def _energy_by_band(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind",), optional=("round_bands", "round"))
    round_bands = fields.raw("round_bands") if fields.has("round_bands") else False
    if not isinstance(round_bands, bool):
        raise DefinitionError(fields.at("round_bands"), "must be true or false")
    return EnergyByBand(round_bands, _rounding(fields))


def _export_credit(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind",), optional=("round",))
    return ExportCredit(_rounding(fields))


def _per_day(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind", "amount"), optional=("round",))
    return PerDay(fields.money("amount"), _rounding(fields))


def _per_period(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind", "amount", "share"), optional=("round",))
    return PerPeriod(fields.money("amount"), fields.choice("share", _SHARES), _rounding(fields))


def _adjust(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind", "name", "percent", "of"), optional=("round",))
    percent = fields.signed("percent")
    if percent <= -100:
        raise DefinitionError(fields.at("percent"), "must be above -100")
    child = _node(fields.child("of"), depth + 1)
    return Adjust(fields.text("name"), percent, child, _rounding(fields))


def _tax(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind", "name", "percent", "mode", "of"), optional=("round",))
    percent = fields.money("percent")
    mode = TaxMode(fields.choice("mode", [m.value for m in TaxMode]))
    child = _node(fields.child("of"), depth + 1)
    return Tax(fields.text("name"), percent, mode, child, _rounding(fields))


def _sum(fields: Fields, depth: int) -> Node:
    fields.only(required=("kind", "of"), optional=("round",))
    children = fields.child("of")
    nodes: dict[str, Node] = {}
    for name, _ in children.items():
        if not _NODE_NAME.match(name):
            raise DefinitionError(children.at(name), "is not a valid name")
        nodes[name] = _node(children.child(name), depth + 1)
    if not nodes:
        raise DefinitionError(children.path, "needs at least one child")
    return Sum(nodes, _rounding(fields))


_NODE_PARSERS: dict[str, Callable[[Fields, int], Node]] = {
    "energy_by_band": _energy_by_band,
    "export_credit": _export_credit,
    "per_day": _per_day,
    "per_period": _per_period,
    "adjust": _adjust,
    "tax": _tax,
    "sum": _sum,
}


def _checks(
    doc: Fields, import_prices: ImportPrices, export_prices: ExportPrices
) -> dict[str, Check]:
    if not doc.has("checks"):
        return {}
    bands = _Bands(_names(import_prices), _names(export_prices))
    fields = doc.child("checks")
    checks: dict[str, Check] = {}
    for name, _ in fields.items():
        if not SLUG.match(name):
            raise DefinitionError(fields.at(name), "is not a valid name")
        checks[name] = _check(fields.child(name), bands)
    return checks


class _Bands(NamedTuple):
    imported: Collection[str]
    exported: Collection[str]


def _names(prices: ImportPrices | ExportPrices) -> set[str]:
    return {prices.base.name, *(zone.name for zone in prices.zones)}


def _check(fields: Fields, bands: _Bands) -> Check:
    fields.only(required=("period_days", "import_kwh_by_band", "export_kwh", "expected_total"))
    # A plain export figure is paid at the base export price. An object names the bands.
    export: Decimal | dict[str, Decimal]
    if isinstance(fields.raw("export_kwh"), Mapping):
        export = _kwh_by_band(fields.child("export_kwh"), bands.exported, "an export band")
    else:
        export = fields.money("export_kwh")
    imported = _kwh_by_band(fields.child("import_kwh_by_band"), bands.imported, "a band")
    return Check(
        period_days=fields.whole("period_days", 1, 366),
        import_kwh_by_band=imported,
        export_kwh=export,
        expected_total=fields.signed("expected_total"),
    )


def _kwh_by_band(by_band: Fields, bands: Collection[str], what: str) -> dict[str, Decimal]:
    kwh: dict[str, Decimal] = {}
    for band, _ in by_band.items():
        if band not in bands:
            raise DefinitionError(by_band.at(band), f"is not {what} of this tariff")
        kwh[band] = by_band.money(band)
    return kwh
