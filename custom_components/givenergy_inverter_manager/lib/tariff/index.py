"""index.py: the tariff index, and reading a definition through it.

The index is a separate JSON file that lists the tariffs on offer, grouped by country and then
provider, so a client can browse, choose or ask for the latest without downloading a definition.
It holds no prices. Each revision of a tariff has its dates, the path of its file and a checksum of
that file. The checksum is computed here over the file's canonical form (keys sorted, no spaces),
never written by hand, and it is kept out of the definition because a file cannot hold its own.

`build_index` makes the index from a set of definition files and refuses a set that disagrees with
itself: a file in the wrong place, revisions of one tariff that overlap, or a `supersedes` that
names no earlier revision. `parse_index` reads one back. A `TariffSource` hands over the index and
the files, whether they come from a folder, a store or the options of this install, and
`load_revision` checks a file against its entry before it is trusted. A local definition has no
checksum until a store exists, so an entry without one is not checked.

Nothing here reads a disk or a network. The source does that.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from .definition import DefinitionError, TariffDefinition
from .definition_parse import COUNTRY, SLUG, Fields, load_json, parse_definition

INDEX_SCHEMA_VERSION = 1

_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_KEY = re.compile(r"^[1-9][0-9]{0,5}$")


class ChecksumMismatch(ValueError):
    """A file does not match the checksum its index entry holds."""


@dataclass(frozen=True)
class RevisionEntry:
    revision: int
    effective_from: date  # included
    effective_to: date | None  # excluded, None while open ended
    path: str
    checksum: str | None  # "sha256:<hex>", None for a local definition


@dataclass(frozen=True)
class TariffEntry:
    id: str
    name: str
    region: str | None
    currency: str
    complete: bool
    latest: int | None  # the revision in force on the day the index was generated
    revisions: Mapping[int, RevisionEntry]


@dataclass(frozen=True)
class ProviderEntry:
    id: str
    name: str
    tariffs: Mapping[str, TariffEntry]


@dataclass(frozen=True)
class TariffIndex:
    generated: date
    countries: Mapping[str, Mapping[str, ProviderEntry]]  # country -> provider id -> entry


class TariffSource(Protocol):
    """Where an index and its definition files come from."""

    def read_index(self) -> str: ...

    def read_file(self, path: str) -> str: ...


@dataclass(frozen=True)
class StaticSource:
    """A source held in memory, for tests and for definitions made in this install."""

    index_text: str
    files: Mapping[str, str]

    def read_index(self) -> str:
        return self.index_text

    def read_file(self, path: str) -> str:
        try:
            return self.files[path]
        except KeyError:
            raise DefinitionError(path, "is not in the source") from None


def canonical_json(text: str) -> str:
    """The document with keys sorted and no spaces, the form a checksum is computed over."""
    return json.dumps(load_json(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum_of(text: str) -> str:
    """The checksum of a definition file, such as `sha256:ab12...`."""
    return "sha256:" + hashlib.sha256(canonical_json(text).encode()).hexdigest()


def expected_path(definition: TariffDefinition) -> str:
    """Where the file for *definition* sits: country/provider/tariff/revision.json."""
    parts = (definition.country.lower(), definition.provider.id, definition.id)
    return "/".join((*parts, f"{definition.revision}.json"))


# Building


def build_index(files: Mapping[str, str], generated: date) -> dict[str, Any]:
    """The index for *files*, a mapping of path to definition text, as a JSON-ready dictionary.

    Raises DefinitionError naming the path of the file that disagrees.
    """
    groups: dict[tuple[str, str, str], dict[int, tuple[str, str, TariffDefinition]]] = {}
    for path, text in sorted(files.items()):
        try:
            definition = parse_definition(load_json(text))
        except DefinitionError as err:
            raise DefinitionError(path, str(err)) from err
        if path != expected_path(definition):
            raise DefinitionError(path, f"belongs at {expected_path(definition)}")
        key = (definition.country, definition.provider.id, definition.id)
        groups.setdefault(key, {})[definition.revision] = (path, text, definition)
    countries: dict[str, Any] = {}
    for (country, provider_id, tariff_id), revisions in sorted(groups.items()):
        _check_revisions(revisions)
        top = revisions[max(revisions)][2]
        provider = countries.setdefault(country, {"providers": {}})["providers"].setdefault(
            provider_id, {"name": top.provider.name, "tariffs": {}}
        )
        provider["tariffs"][tariff_id] = _tariff_entry(revisions, top, generated)
    return {
        "schema": INDEX_SCHEMA_VERSION,
        "generated": generated.isoformat(),
        "countries": countries,
    }


def _check_revisions(revisions: Mapping[int, tuple[str, str, TariffDefinition]]) -> None:
    ordered = sorted((d.effective_from, d.effective_to, path) for path, _, d in revisions.values())
    for (_, end, path), (start, _, later) in zip(ordered, ordered[1:], strict=False):
        if end is None or end > start:
            raise DefinitionError(later, f"overlaps the dates of {path}")
    for path, _, definition in revisions.values():
        earlier = definition.supersedes
        if earlier is not None and earlier not in revisions:
            raise DefinitionError(path, f"supersedes revision {earlier}, which is not here")


def _tariff_entry(
    revisions: Mapping[int, tuple[str, str, TariffDefinition]],
    top: TariffDefinition,
    generated: date,
) -> dict[str, Any]:
    in_force = [
        number
        for number, (_, _, d) in revisions.items()
        if _in_force(d.effective_from, d.effective_to, generated)
    ]
    return {
        "name": top.name,
        "region": top.region,
        "currency": top.currency,
        "completeness": "complete" if top.complete else "partial",
        "latest": max(in_force) if in_force else None,
        "revisions": {
            str(number): {
                "effective_from": definition.effective_from.isoformat(),
                "effective_to": _iso(definition.effective_to),
                "path": path,
                "checksum": checksum_of(text),
            }
            for number, (path, text, definition) in sorted(revisions.items(), reverse=True)
        },
    }


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _in_force(start: date, end: date | None, on: date) -> bool:
    return start <= on and (end is None or on < end)


# Reading


def parse_index(text: str) -> TariffIndex:
    """Read index text. Raises DefinitionError for anything not valid."""
    doc = Fields(load_json(text), "")
    doc.only(required=("schema", "generated", "countries"))
    doc.whole("schema", INDEX_SCHEMA_VERSION, INDEX_SCHEMA_VERSION)
    countries = doc.child("countries")
    parsed: dict[str, Mapping[str, ProviderEntry]] = {}
    for code, _ in countries.items():
        if not COUNTRY.match(code):
            raise DefinitionError(countries.at(code), "must be a two letter country code")
        parsed[code] = _providers(countries.child(code))
    return TariffIndex(doc.day("generated"), parsed)


def _providers(country: Fields) -> dict[str, ProviderEntry]:
    country.only(required=("providers",))
    providers = country.child("providers")
    found: dict[str, ProviderEntry] = {}
    for provider_id, _ in providers.items():
        _slug(providers, provider_id)
        fields = providers.child(provider_id)
        fields.only(required=("name", "tariffs"))
        tariffs = fields.child("tariffs")
        found[provider_id] = ProviderEntry(
            provider_id,
            fields.text("name"),
            {name: _tariff(tariffs, name) for name, _ in tariffs.items()},
        )
    return found


def _tariff(parent: Fields, tariff_id: str) -> TariffEntry:
    _slug(parent, tariff_id)
    fields = parent.child(tariff_id)
    fields.only(
        required=("name", "region", "currency", "completeness", "latest", "revisions")
    )
    revisions = fields.child("revisions")
    parsed = [_revision(revisions, key) for key, _ in revisions.items()]
    entries = {entry.revision: entry for entry in parsed}
    if not entries:
        raise DefinitionError(revisions.path, "needs at least one revision")
    latest = None if fields.raw("latest") is None else fields.whole("latest", 1, 1_000_000)
    if latest is not None and latest not in entries:
        raise DefinitionError(fields.at("latest"), "is not one of the revisions")
    return TariffEntry(
        tariff_id,
        fields.text("name"),
        fields.optional_text("region"),
        fields.text("currency"),
        fields.choice("completeness", ("complete", "partial")) == "complete",
        latest,
        entries,
    )


def _revision(parent: Fields, key: str) -> RevisionEntry:
    if not _REVISION_KEY.match(key):
        raise DefinitionError(parent.at(key), "must be a revision number")
    fields = parent.child(key)
    fields.only(required=("effective_from", "effective_to", "path", "checksum"))
    start, end = fields.day("effective_from"), fields.optional_day("effective_to")
    if end is not None and end <= start:
        raise DefinitionError(fields.at("effective_to"), "must be after effective_from")
    checksum = fields.optional_text("checksum")
    if checksum is not None and not _CHECKSUM.match(checksum):
        raise DefinitionError(fields.at("checksum"), "must be sha256: and 64 hex digits")
    return RevisionEntry(int(key), start, end, fields.text("path"), checksum)


def _slug(parent: Fields, name: str) -> None:
    if not SLUG.match(name):
        raise DefinitionError(parent.at(name), "must be lowercase letters, digits and hyphens")


# Choosing


def find_tariff(index: TariffIndex, country: str, provider_id: str, tariff_id: str) -> TariffEntry:
    """The tariff at that place in the index. Raises LookupError when there is none."""
    try:
        return index.countries[country][provider_id].tariffs[tariff_id]
    except KeyError:
        raise LookupError(f"no tariff {country}/{provider_id}/{tariff_id} in the index") from None


def revision_in_force(tariff: TariffEntry, on: date) -> RevisionEntry | None:
    """The revision that prices *on*, or None. The dates never overlap, so there is at most one."""
    for entry in tariff.revisions.values():
        if _in_force(entry.effective_from, entry.effective_to, on):
            return entry
    return None


def load_revision(source: TariffSource, entry: RevisionEntry) -> TariffDefinition:
    """Read the file for *entry*, check it, and return the definition.

    Raises ChecksumMismatch when the file is not the one the index describes, and DefinitionError
    when it is not a valid definition or disagrees with the entry's revision or dates.
    """
    text = source.read_file(entry.path)
    if entry.checksum is not None and checksum_of(text) != entry.checksum:
        raise ChecksumMismatch(f"{entry.path} does not match its checksum")
    definition = parse_definition(load_json(text))
    if (definition.revision, definition.effective_from, definition.effective_to) != (
        entry.revision,
        entry.effective_from,
        entry.effective_to,
    ):
        raise DefinitionError(entry.path, "does not agree with its index entry")
    return definition
