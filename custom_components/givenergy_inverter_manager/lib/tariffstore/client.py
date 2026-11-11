"""Find, fetch and check tariffs from the store. Standard library only.

A `Store` is given one function, `read(path) -> bytes`, that returns a file under `tariffs/`. It
may read a folder, a URL or a test dictionary. The store walks three levels and checks each one
against the level above before it is trusted:

    index.json                      the countries, each with the checksum of its index
    <cc>/index.json                 the country's values, then providers, tariffs and revisions
    <cc>/<provider>/<tariff>/<n>.json   one revision of one tariff

`definition()` returns the document the bill engine reads (`lib.tariff.load_definition`), so a
caller goes from a country code, a provider, a tariff and a date to a priced bill.

What the store hands over is kept in a cache, laid out like the store itself. `FolderCache` keeps
it on disk, so a tariff is downloaded once, and a caller that has used a tariff can price it again
with no network. No separate list of what is held is kept: the cached indexes carry the checksum
of every file, so a cached file is used exactly when it is the one its index describes. Only the
countries index has an age. `custom_definition()` prices a tariff the store does not hold.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from .compile import CompileError, compile_area
from .index import SCHEMA, block_of
from .schema import Doc, checksum, validate_country, validate_tariff

OPEN = "9999-12-31"
USER_AGENT = "tariffstore-client/1"
DAY_SECONDS = 86400.0
ROOT = "index.json"
SAFE_PATH = re.compile(r"^[a-z0-9-]+(/[a-z0-9-]+)*\.json$")
CUSTOM = "custom"
CUSTOM_SOURCE = {"id": CUSTOM, "url": "https://example.invalid/custom"}


class StoreError(LookupError):
    """Something asked for is not in the store, or a file is not the one its index describes."""


def folder_reader(tariffs: Path) -> Callable[[str], bytes]:
    return lambda path: (Path(tariffs) / path).read_bytes()


def url_reader(base: str, timeout: float = 30) -> Callable[[str], bytes]:
    """Read from an https base such as a raw file host. `base` is the address of `tariffs/`."""
    if not base.startswith("https://"):
        raise ValueError("the store is read over https only")

    def read(path: str) -> bytes:
        request = urllib.request.Request(f"{base.rstrip('/')}/{path}",
                                         headers={"User-Agent": USER_AGENT})
        # The base is https, checked above, so no file or other scheme can reach this call.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            body: bytes = response.read()
        return body
    return read


def _safe(path: str) -> str:
    if not SAFE_PATH.match(path):
        raise StoreError(f"{path}: not a path inside the store")
    return path


class MemoryCache:
    """Keeps what was read for as long as the object lives."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._files: dict[str, tuple[bytes, float]] = {}
        self._clock = clock

    def get(self, path: str) -> bytes | None:
        held = self._files.get(path)
        return held[0] if held else None

    def put(self, path: str, raw: bytes) -> None:
        self._files[path] = (raw, self._clock())

    def age(self, path: str) -> float | None:
        """Seconds since the file was kept, or None when it is not held."""
        held = self._files.get(path)
        return self._clock() - held[1] if held else None


class FolderCache:
    """Keeps what was read in a folder on disk, at the same paths as the store, so it lasts
    between runs and can be read by hand. Deleting the folder, or any file in it, is safe."""

    def __init__(self, folder: Path | str, clock: Callable[[], float] = time.time) -> None:
        self._folder = Path(folder)
        self._clock = clock

    def get(self, path: str) -> bytes | None:
        try:
            return (self._folder / _safe(path)).read_bytes()
        except OSError:
            return None

    def put(self, path: str, raw: bytes) -> None:
        target = self._folder / _safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the file and moved into place, so a reader never sees half a file.
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(raw)
        os.replace(partial, target)

    def age(self, path: str) -> float | None:
        try:
            return self._clock() - (self._folder / _safe(path)).stat().st_mtime
        except OSError:
            return None


class Store:
    """The tariff store, read through `read`, with what it reads kept in `cache`.

    The countries index is read again once it is older than `max_age` seconds. Everything below
    it is read again only when its checksum in the level above has changed. When the store cannot
    be reached, what the cache holds is used and `offline` is true."""

    def __init__(self, read: Callable[[str], bytes],
                 cache: MemoryCache | FolderCache | None = None, *,
                 max_age: float = DAY_SECONDS) -> None:
        self._read = read
        self._cache = cache if cache is not None else MemoryCache()
        self._max_age = max_age
        self._root: Doc | None = None
        self._countries: dict[str, Doc] = {}
        self._forced = False
        self.offline = False

    @classmethod
    def cached(cls, base: str, folder: Path | str, *, max_age: float = DAY_SECONDS) -> Store:
        """A store read from an https address, with a cache in `folder`."""
        return cls(url_reader(base), FolderCache(folder), max_age=max_age)

    def _parsed(self, path: str, raw: bytes) -> Doc:
        try:
            doc = json.loads(raw)
        except ValueError as error:
            raise StoreError(f"{path}: not JSON ({error})") from error
        if not isinstance(doc, dict):
            raise StoreError(f"{path}: not a JSON object")
        return doc

    def _fetch(self, path: str) -> bytes:
        try:
            return self._read(_safe(path))
        except OSError as error:
            raise StoreError(f"{path}: cannot be read ({error})") from error

    def _checked(self, path: str, wanted: str) -> Doc:
        """The file at `path` whose checksum is `wanted`: from the cache when it holds that very
        file, else from the store, and then kept."""
        held = self._cache.get(path)
        if held is not None:
            kept: Doc | None
            try:
                kept = self._parsed(path, held)
            except StoreError:
                kept = None
            if kept is not None and checksum(kept) == wanted:
                return kept
        raw = self._fetch(path)
        doc = self._parsed(path, raw)
        if checksum(doc) != wanted:
            raise StoreError(f"{path}: does not match its checksum")
        self._cache.put(path, raw)
        return doc

    def _read_root(self) -> Doc:
        held, age = self._cache.get(ROOT), self._cache.age(ROOT)
        if held is not None and not self._forced and age is not None and age <= self._max_age:
            return self._parsed(ROOT, held)
        try:
            raw = self._fetch(ROOT)
            root = self._parsed(ROOT, raw)
        except StoreError:
            # Unreachable, or an answer that is not the index (a sign-in page, say).
            if held is None:
                raise
            self.offline = True
            return self._parsed(ROOT, held)
        self._cache.put(ROOT, raw)
        self._forced = self.offline = False
        return root

    def refresh(self) -> None:
        """Read the countries index from the store again on the next call, whatever its age.
        Files whose checksum has not changed are not downloaded again."""
        self._root, self._countries = None, {}
        self._forced = True

    # Finding

    def countries(self) -> dict[str, Doc]:
        """{country code: {availability, reason, providers, tariffs}} for every country listed."""
        if self._root is None:
            root = self._read_root()
            if root.get("schema") != SCHEMA or not isinstance(root.get("countries"), dict):
                raise StoreError(f"index.json: not a schema {SCHEMA} countries index")
            self._root = root
        countries: dict[str, Doc] = self._root["countries"]
        return countries

    def country(self, code: str) -> Doc:
        """The country's index, checked against the countries index: its values and its tariffs."""
        code = code.upper()
        if code not in self._countries:
            entry = self.countries().get(code)
            if entry is None or "path" not in entry:
                reason = f": {entry['reason']}" if entry else ""
                raise StoreError(f"{code}: no tariffs are held{reason}")
            self._countries[code] = self._checked(entry["path"], entry["checksum"])
        return self._countries[code]

    def providers(self, code: str) -> dict[str, str]:
        """{provider id: provider name} in one country."""
        return {key: p["name"] for key, p in self.country(code)["providers"].items()}

    def tariffs(self, code: str, provider: str, *, direction: str = "import",
                on: date | None = None) -> dict[str, str]:
        """{tariff id: name} for one provider. `on` keeps only tariffs with a revision in force."""
        try:
            entries = self.country(code)["providers"][provider]["tariffs"]
        except KeyError:
            raise StoreError(f"{code}: no provider {provider}") from None
        return {key: t["name"] for key, t in entries.items()
                if t.get("direction", "import") == direction
                and (on is None or _in_force(t, on) is not None)}

    def revision(self, code: str, provider: str, tariff: str, on: date) -> tuple[int, Doc]:
        """(revision number, its index entry) in force on a day."""
        try:
            entry = self.country(code)["providers"][provider]["tariffs"][tariff]
        except KeyError:
            raise StoreError(f"{code}: no tariff {provider}/{tariff}") from None
        number = _in_force(entry, on)
        if number is None:
            raise StoreError(f"{code}/{provider}/{tariff}: no revision is in force on {on}")
        return number, entry["revisions"][str(number)]

    # Fetching

    def tariff(self, code: str, provider: str, tariff: str, on: date) -> tuple[int, Doc]:
        """(revision number, tariff file) in force on a day, checked against its checksum and
        valid."""
        number, entry = self.revision(code, provider, tariff, on)
        path = f"{code.lower()}/{provider}/{tariff}/{number}.json"
        doc = self._checked(path, entry["checksum"])
        errors = validate_tariff(doc)
        if errors:
            raise StoreError(f"{path}: " + "; ".join(errors))
        return number, doc

    def fetch_country(self, code: str, *, on: date | None = None) -> int:
        """Bring a whole country into the cache, for comparing many tariffs or for use with no
        network. `on` keeps it to the revisions in force on that day. Returns the number of
        tariff files now held."""
        count = 0
        for provider, entry in self.country(code)["providers"].items():
            for tariff, listed in entry["tariffs"].items():
                for number, revision in listed["revisions"].items():
                    if on is not None and _in_force(listed, on) != int(number):
                        continue
                    path = f"{code.lower()}/{provider}/{tariff}/{number}.json"
                    self._checked(path, revision["checksum"])
                    count += 1
        return count

    def areas(self, code: str, provider: str, tariff: str, on: date) -> dict[str, str]:
        """{area key: label} a customer chooses from. A tariff with one price has the area `all`."""
        _, doc = self.tariff(code, provider, tariff, on)
        return {key: row.get("label", doc["name"]) for key, row in doc["areas"].items()}

    def _export_file(self, code: str, target: str, on: date) -> Doc:
        """The stored export tariff named `provider-id/tariff-id`."""
        provider, _, tariff = target.partition("/")
        doc = self.tariff(code, provider, tariff, on)[1]
        if doc.get("direction") != "export":
            raise StoreError(f"{target}: not an export tariff")
        return doc

    def definition(self, code: str, provider: str, tariff: str, on: date, *,  # noqa: PLR0913
                   area: str = "all", export: str | None = None) -> Doc:
        """The engine's definition for one area of a tariff on a day.

        `export` names an export tariff as `provider-id/tariff-id` to pay for exported energy. Left
        out, the export tariff the import tariff itself names is used, if it names one."""
        code = code.upper()
        number, doc = self.tariff(code, provider, tariff, on)
        if doc.get("direction") == "export":
            raise StoreError(f"{provider}/{tariff}: an export tariff is paired with an import "
                             "tariff, it has no bill of its own")
        target = export or doc.get("export")
        export_file = self._export_file(code, target, on) if target else None
        _, entry = self.revision(code, provider, tariff, on)
        meta = {"country": code, "provider": provider, "tariff": tariff, "revision": number,
                "effective_to": entry["effective_to"]}
        return compile_area(doc, area, block=block_of(self.country(code)), meta=meta,
                            on=on.isoformat(), export_file=export_file)

    # A tariff the store does not hold

    def _custom_export(self, code: str, export: str | Doc | None, on: date) -> Doc | None:
        if export is None:
            return None
        if isinstance(export, str):
            provider, _, tariff = export.partition("/")
            found = self.tariff(code, provider, tariff, on)[1]
        else:
            found = _custom(export)
        if found.get("direction") != "export":
            raise StoreError("custom tariff: the export given is not an export tariff")
        return found

    def custom_definition(self, code: str, doc: Doc, on: date, *,  # noqa: PLR0913
                          area: str = "all", export: str | Doc | None = None,
                          block: Doc | None = None) -> Doc:
        """The engine's definition for a tariff the caller supplies, written like a tariff file.

        The country's currency, time zone, tax and standard bill come from the store, so the
        caller types only names, dates, bands and prices. `provider` and `source` may be left
        out. `export` is a stored export tariff (`provider-id/tariff-id`) or a custom export
        file. For a country the store does not hold, pass its values as `block`, written like the
        top of a country index. The document is checked by the same rules as a stored tariff."""
        code = code.upper()
        doc = _custom(doc)
        if doc.get("direction") == "export":
            raise StoreError("custom tariff: pass an export tariff as `export`, with an import "
                             "tariff")
        if block is None:
            block = block_of(self.country(code))
        else:
            _refuse("custom country", validate_country(block))
        export_file = self._custom_export(code, export, on)
        meta = {"country": code, "provider": CUSTOM, "tariff": CUSTOM, "revision": 1,
                "effective_to": doc.get("effective_to")}
        try:
            out = compile_area(doc, area, block=block, meta=meta, on=on.isoformat(),
                               export_file=export_file)
        except CompileError as error:
            raise StoreError(f"custom tariff: {error}") from error
        if doc["source"] == CUSTOM_SOURCE:
            out["source_url"] = None
        return out


def _refuse(what: str, errors: list[str]) -> None:
    if errors:
        raise StoreError(f"{what}: " + "; ".join(errors))


def _custom(doc: Doc) -> Doc:
    """A supplied tariff with the fields a person need not type filled in, then validated."""
    if not isinstance(doc, dict):
        raise StoreError("custom tariff: not a JSON object")
    full = {"schema": 1, "provider": "Custom", "source": dict(CUSTOM_SOURCE), **doc}
    _refuse("custom tariff", validate_tariff(full))
    return full


def _in_force(entry: Doc, on: date) -> int | None:
    day = on.isoformat()
    for number, revision in entry["revisions"].items():
        if revision["effective_from"] <= day < (revision["effective_to"] or OPEN):
            return int(number)
    return None
