"""Build and check the indexes. Pure functions over parsed JSON, standard library only.

A country index is the country block (the values every tariff in the country shares, edited by
hand) followed by `providers`, the tariff collection, which is derived from the tariff files and
from nothing else. So the same files always give the same index, byte for byte.
"""
from __future__ import annotations

import re

from .compile import CompileError, check_references, compile_area
from .schema import (
    SLUG,
    Doc,
    checksum,
    validate_country,
    validate_tariff,
    validate_unavailable,
)

SCHEMA = 1
PATH = re.compile(r"^([a-z0-9-]+)/([a-z0-9-]+)/([1-9][0-9]*)\.json$")
OPEN = "9999-12-31"
Revisions = dict[int, Doc]
Tariffs = dict[tuple[str, str], Revisions]


def block_of(index: Doc) -> Doc:
    """The hand-maintained part of a country index: everything but the tariff collection."""
    return {k: v for k, v in index.items() if k != "providers"}


def group(files: dict[str, Doc]) -> tuple[Tariffs, list[str]]:
    """{(provider id, tariff id): {revision: file}}, and the paths that are not
    provider/tariff/n.json."""
    tariffs: Tariffs = {}
    bad = []
    for path in sorted(files):
        match = PATH.match(path)
        if not match or not SLUG.match(match.group(1)) or not SLUG.match(match.group(2)):
            bad.append(f"{path}: must be <provider-id>/<tariff-id>/<revision>.json")
            continue
        tariffs.setdefault((match.group(1), match.group(2)), {})[int(match.group(3))] = files[path]
    return tariffs, bad


def end_of(revisions: Revisions, number: int) -> str | None:
    """When a revision stops: its own `effective_to`, or else the day the next revision starts."""
    own: str | None = revisions[number].get("effective_to")
    following = revisions.get(number + 1)
    start: str | None = following["effective_from"] if following else None
    return own or start


def _revision_problems(key: str, revisions: Revisions) -> list[str]:
    numbers = sorted(revisions)
    if numbers != list(range(1, len(numbers) + 1)):
        return [f"{key}: revisions must be numbered 1, 2, 3 with none missing"]
    problems = []
    for number in numbers[1:]:
        before, this = revisions[number - 1], revisions[number]
        if this["effective_from"] <= before["effective_from"]:
            problems.append(f"{key}/{number}: must start after revision {number - 1}")
        elif before.get("effective_to", this["effective_from"]) > this["effective_from"]:
            problems.append(f"{key}/{number}: starts before revision {number - 1} ends")
        if this.get("direction") != before.get("direction"):
            problems.append(f"{key}/{number}: a tariff cannot change direction")
    return problems


def _overlaps(revisions: Revisions, other: Revisions) -> bool:
    spans = [(r["effective_from"], end_of(revs, n) or OPEN)
             for revs in (revisions, other) for n, r in revs.items()]
    mine, theirs = spans[:len(revisions)], spans[len(revisions):]
    return any(a < d and c < b for a, b in mine for c, d in theirs)


def _export_problem(doc: Doc, number: int, tariffs: Tariffs, code: str) -> list[str]:
    """What is wrong with the export tariff an import file names, if it names one."""
    target = doc.get("export")
    if not target:
        return []
    provider, _, tariff = target.partition("/")
    other = tariffs.get((provider, tariff))
    if not other:
        return [f"export {target} does not exist in {code}"]
    if other[max(other)].get("direction") != "export":
        return [f"export {target} is not an export file"]
    if not _overlaps({number: doc}, other):
        return [f"export {target} has no revision overlapping its dates"]
    return []


def _compile_problems(doc: Doc, block: Doc, meta: Doc) -> list[str]:
    """Each area of an import file must compile into a definition the engine reads."""
    found = []
    for area in doc["areas"]:
        try:
            compile_area(doc, area, block=block, meta=meta, on=doc["effective_from"])
        except (CompileError, KeyError) as error:
            found.append(f"area {area} does not compile: {error}")
    return found


def _file_problems(doc: Doc, meta: Doc, block: Doc, tariffs: Tariffs) -> list[str]:
    found = check_references(doc, block)
    found += _export_problem(doc, meta["revision"], tariffs, meta["country"])
    if doc.get("direction") != "export":
        found += _compile_problems(doc, block, meta)
    return found


def problems(code: str, block: Doc, files: dict[str, Doc]) -> list[str]:
    """Everything wrong with one country's block and tariff files. Empty means it can be indexed."""
    found = [f"country block: {e}" for e in validate_country(block)]
    if not found and block["country"] != code:
        found.append(f"country block: country must be {code}")
    tariffs, bad = group(files)
    found += bad
    for path in sorted(files):
        found += [f"{path}: {e}" for e in validate_tariff(files[path])]
    if found:
        return found
    for (provider, tariff), revisions in tariffs.items():
        key = f"{provider}/{tariff}"
        found += _revision_problems(key, revisions)
        for number, doc in revisions.items():
            meta = {"country": code, "provider": provider, "tariff": tariff, "revision": number}
            found += [f"{key}/{number}: {p}" for p in _file_problems(doc, meta, block, tariffs)]
    return found


def _tariff_entry(revisions: Revisions) -> Doc:
    latest = revisions[max(revisions)]
    entry: Doc = {"name": latest["name"]}
    if latest.get("direction") == "export":
        entry["direction"] = "export"
    entry["revisions"] = {
        str(n): {"effective_from": doc["effective_from"], "effective_to": end_of(revisions, n),
                 "checksum": checksum(doc)} for n, doc in sorted(revisions.items())}
    return entry


def country_index(block: Doc, files: dict[str, Doc]) -> Doc:
    """The country index: the block, then the tariff collection derived from the files."""
    providers: dict[str, Doc] = {}
    for (provider, tariff), revisions in group(files)[0].items():
        latest = revisions[max(revisions)]
        entry = _tariff_entry(revisions)
        slot = providers.setdefault(
            provider, {"name": latest["provider"], "newest": "", "tariffs": {}})
        if latest["effective_from"] >= slot["newest"]:  # the newest file names the provider
            slot["name"], slot["newest"] = latest["provider"], latest["effective_from"]
        slot["tariffs"][tariff] = entry
    for slot in providers.values():
        del slot["newest"]
    return {**block, "schema": SCHEMA, "providers": providers}


def _root_entry(code: str, index: Doc) -> Doc:
    entry: Doc = {"availability": index.get("availability", "available"),
                  "path": f"{code.lower()}/index.json", "checksum": checksum(index),
                  "providers": len(index["providers"]),
                  "tariffs": sum(len(p["tariffs"]) for p in index["providers"].values())}
    if index.get("reason"):
        entry["reason"] = index["reason"]
    return entry


def root_index(countries: dict[str, Doc], unavailable: Doc) -> Doc:
    """The countries index: one small entry per country, so a client sees what changed."""
    errors = validate_unavailable(unavailable)
    clash = sorted(set(unavailable.get("countries", {})) & set(countries)) if not errors else []
    if errors or clash:
        raise ValueError("unavailable.json: "
                         + "; ".join(errors or [f"{c} has tariff files" for c in clash]))
    out = {code: _root_entry(code, index) for code, index in countries.items()}
    for code, entry in unavailable["countries"].items():
        out[code] = {"availability": "unavailable", "reason": entry["reason"],
                     "checked": entry["checked"]}
    return {"schema": SCHEMA, "countries": dict(sorted(out.items()))}
