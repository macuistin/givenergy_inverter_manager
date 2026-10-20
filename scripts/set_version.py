#!/usr/bin/env python3
"""Set, or check, the release version in the six places that state it.

The places are pyproject.toml, manifest.json, const.INTEGRATION_VERSION, the "Current version"
line of README.md, the "This documentation matches version" line of docs/index.md and the
"The current release is" line of REQUIREMENTS.md.

A version is PEP 440 with an optional beta or release candidate suffix: 0.18.0, 0.18.0b1,
0.18.0rc2. A git tag is that version behind a "v" (v0.18.0b1). Both are accepted everywhere.

Usage:
    python scripts/set_version.py 0.18.0b1            # write the version to all six places
    python scripts/set_version.py v0.18.0b1           # the same, from a tag
    python scripts/set_version.py --check v0.18.0b1   # exit 1 unless all six equal the tag
    python scripts/set_version.py --check             # exit 1 unless the six agree
    python scripts/set_version.py --tag               # print the tag for the version in the files
    python scripts/set_version.py --notes v0.18.0     # print that version's changelog section

A final release needs a "## vX.Y.Z" section in CHANGELOG.md. A beta or release candidate
without one uses the "## Unreleased" section.

Exit codes: 0 done, 1 a place differs or is missing, 2 the argument is not a version.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 0.18.0, 0.18.0b1, 0.18.0rc2. Release segments are numbers, the suffix is optional.
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?"
_VERSION_ONLY = re.compile(VERSION)


@dataclass(frozen=True)
class Place:
    """One file that states the version, and the pattern that finds it.

    The pattern has two groups: the text before the version and the version itself.
    """

    name: str
    path: str
    pattern: re.Pattern[str]


PLACES: tuple[Place, ...] = (
    Place("pyproject.toml", "pyproject.toml", re.compile(rf'(?m)^(version = ")({VERSION})(?=")')),
    Place(
        "manifest.json",
        "custom_components/givenergy_inverter_manager/manifest.json",
        re.compile(rf'(?m)^(\s*"version": ")({VERSION})(?=")'),
    ),
    Place(
        "const.INTEGRATION_VERSION",
        "custom_components/givenergy_inverter_manager/const.py",
        re.compile(rf'(?m)^(INTEGRATION_VERSION = ")({VERSION})(?=")'),
    ),
    Place("README.md", "README.md", re.compile(rf"(Current version: )({VERSION})")),
    Place(
        "docs/index.md",
        "docs/index.md",
        re.compile(rf"(This documentation matches version )({VERSION})"),
    ),
    Place(
        "REQUIREMENTS.md",
        "REQUIREMENTS.md",
        re.compile(rf"(The current release is )({VERSION})"),
    ),
)


class VersionError(Exception):
    """The argument is not a version or a tag."""


def normalise(value: str) -> str:
    """The version in a version or a tag: a leading "v" is dropped."""
    version = value.strip().removeprefix("v")
    if not _VERSION_ONLY.fullmatch(version):
        raise VersionError(
            f"{value!r} is not a version. Use 0.18.0, 0.18.0b1 or 0.18.0rc1, with an optional v."
        )
    return version


def tag_for(version: str) -> str:
    return f"v{version}"


def read_versions(root: Path = ROOT) -> dict[str, str | None]:
    """The version each place states, or None where the pattern finds nothing."""
    found: dict[str, str | None] = {}
    for place in PLACES:
        match = place.pattern.search((root / place.path).read_text(encoding="utf-8"))
        found[place.name] = match.group(2) if match else None
    return found


def write_version(version: str, root: Path = ROOT) -> list[str]:
    """Write *version* to every place. Returns the places that could not be found.

    Nothing is written when any place is missing, so a failed run leaves the tree as it was.
    """
    texts = {place: (root / place.path).read_text(encoding="utf-8") for place in PLACES}
    missing = [place.name for place, text in texts.items() if not place.pattern.search(text)]
    if missing:
        return missing
    for place, text in texts.items():
        updated = place.pattern.sub(lambda m: f"{m.group(1)}{version}", text, count=1)
        (root / place.path).write_text(updated, encoding="utf-8")
    return []


def mismatches(expected: str | None, root: Path = ROOT) -> list[str]:
    """The places that do not state *expected*, or that do not agree when it is None."""
    versions = read_versions(root)
    absent = [f"{name}: no version found" for name, found in versions.items() if found is None]
    if absent:
        return absent
    target = expected if expected is not None else next(iter(versions.values()))
    return [
        f"{name}: {found}, expected {target}"
        for name, found in versions.items()
        if found != target
    ]


def release_notes(version: str, root: Path = ROOT) -> str | None:
    """The CHANGELOG.md section to publish for a version, without its heading, or None.

    A beta or release candidate with no section of its own gets the Unreleased one.
    """
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [rf"v{re.escape(version)}"]
    if re.search(r"(?:a|b|rc)[0-9]+$", version):
        headings.append("Unreleased")
    for heading in headings:
        match = re.search(rf"(?ms)^## {heading}\n(.*?)(?=^## |\Z)", text)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", nargs="?", help="a version or a tag, for example v0.18.0b1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check instead of writing")
    mode.add_argument("--tag", action="store_true", help="print the tag of the files' version")
    mode.add_argument("--notes", action="store_true", help="print the version's changelog section")
    return parser


def _report(problems: list[str]) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def _check(version: str | None, root: Path) -> int:
    status = _report(mismatches(normalise(version) if version else None, root))
    if status == 0:
        print(f"All {len(PLACES)} places agree.")
    return status


def _print_tag(root: Path) -> int:
    status = _report(mismatches(None, root))
    if status == 0:
        print(tag_for(next(iter(read_versions(root).values()))))
    return status


def _notes(version: str | None, root: Path) -> int:
    clean = normalise(version) if version else None
    if clean is None:
        raise VersionError("--notes needs a version or a tag.")
    if (notes := release_notes(clean, root)) is None:
        return _report([f"CHANGELOG.md: no section for v{clean}"])
    print(notes)
    return 0


def _write(version: str, root: Path) -> int:
    clean = normalise(version)
    missing = write_version(clean, root)
    status = _report([f"{name}: no version found, nothing was written" for name in missing])
    if status == 0:
        print(f"Set {clean} in {len(PLACES)} places. The tag is {tag_for(clean)}.")
    return status


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.tag:
            return _print_tag(root)
        if args.check:
            return _check(args.version, root)
        if args.notes:
            return _notes(args.version, root)
        if args.version is None:
            parser.error("a version is required unless --check or --tag is given")
        return _write(args.version, root)
    except VersionError as err:
        print(err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
