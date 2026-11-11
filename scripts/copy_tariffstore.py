"""Copy the tariff libraries and their tests from a checkout of the tariff store.

    python scripts/copy_tariffstore.py ../utility-tariffs
    python scripts/copy_tariffstore.py --check ../utility-tariffs

The tariff store (macuistin/utility-tariffs) is where all tariff and billing code is written:
lib/tariff (the bill engine), lib/timeutil (its clock helpers) and lib/tariffstore (the store
client). Their folders in this repository are never edited by hand. This writes each package as
it stands at the checkout's HEAD commit and rewrites its UPSTREAM.json, which
tests/lib/test_upstream.py checks the files against. It also writes the store's own tests of
each package, with their imports pointed at the copy, so a change there is tested here.
`.github/workflows/tariffstore-copy.yml` runs this weekly and opens a pull request.

With --check nothing is written. It exits 1 and names each file that differs from the checkout,
which is how the release workflow refuses to publish a copy that is behind the store.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "custom_components" / "givenergy_inverter_manager" / "lib"
TESTS = ROOT / "tests" / "lib"
HEADER = "# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.\n"
HERE = "custom_components.givenergy_inverter_manager.lib"
REWRITES = (
    ("from lib.", f"from {HERE}."),
    ("from lib import", f"from {HERE} import"),
    ("from tests.tariff.", "from tests.lib.tariff."),
)
# The store's tests of its client build a store on disk with its build script. Here
# `tests/lib/tariffstore/building.py` does it.
CLIENT_REWRITES = (
    ("from tests.fixtures import", "from .fixtures import"),
    ("from scripts import build\n", "from .building import build_store\n"),
    ("self.assertEqual(build.main([], self.tariffs), 0)", "build_store(self.tariffs)"),
)
CLIENT_TESTS = (
    "fixtures.py",
    "test_client.py",
    "test_compile.py",
    "test_index.py",
    "test_schema.py",
)


@dataclass(frozen=True)
class Package:
    """One folder of the store's lib/, and where the store keeps its tests."""

    name: str
    tests: str
    test_files: tuple[str, ...] = ()
    rewrites: tuple[tuple[str, str], ...] = ()

    def test_names(self, checkout: Path) -> list[str]:
        """The test files to copy: the ones named, or every module in the store's folder."""
        if self.test_files:
            return list(self.test_files)
        found = (checkout / self.tests).glob("*.py")
        return sorted(p.name for p in found if not p.name.startswith("__"))

    def ported(self, text: str) -> str:
        """A test file of the store, with its imports pointed at the copy."""
        for old, new in (*self.rewrites, *REWRITES):
            text = text.replace(old, new)
        return HEADER + text


PACKAGES = (
    Package("tariff", "tests/tariff"),
    Package("timeutil", "tests/timeutil"),
    Package("tariffstore", "tests", CLIENT_TESTS, CLIENT_REWRITES),
)


def _sources(folder: Path) -> list[Path]:
    """The files of a package that are copied: its modules and its notes."""
    return sorted([*folder.glob("*.py"), *folder.glob("*.md")])


def copy_library(source: Path, target: Path) -> dict[str, str]:
    """Replace the library files in target with source's. Returns {file name: SHA-256}."""
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.py"):
        old.unlink()
    files = {}
    for path in _sources(source):
        data = path.read_bytes()
        (target / path.name).write_bytes(data)
        files[path.name] = hashlib.sha256(data).hexdigest()
    return files


def copy_tests(package: Package, checkout: Path) -> None:
    target = TESTS / package.name
    target.mkdir(parents=True, exist_ok=True)
    for name in package.test_names(checkout):
        text = (checkout / package.tests / name).read_text(encoding="utf-8")
        (target / name).write_text(package.ported(text), encoding="utf-8")


def copy_package(package: Package, checkout: Path, commit: str) -> int:
    """Copy one package, its tests and its record. Returns the number of library files."""
    path = f"lib/{package.name}"
    files = copy_library(checkout / path, LIB / package.name)
    copy_tests(package, checkout)
    upstream = {
        "repository": "macuistin/utility-tariffs",
        "path": path,
        "commit": commit,
        "files": files,
    }
    record = LIB / package.name / "UPSTREAM.json"
    record.write_text(json.dumps(upstream, indent=2) + "\n", encoding="utf-8")
    return len(files)


def _wanted(package: Package, checkout: Path) -> dict[Path, bytes | None]:
    """Each file of a package here, with the bytes the checkout says it should hold."""
    source, target = checkout / "lib" / package.name, LIB / package.name
    names = {p.name for p in _sources(source)} | {p.name for p in target.glob("*.py")}
    wanted = {target / name: _bytes(source / name) for name in sorted(names)}
    for name in package.test_names(checkout):
        text = (checkout / package.tests / name).read_text("utf-8")
        wanted[TESTS / package.name / name] = package.ported(text).encode()
    return wanted


def behind(checkout: Path) -> list[str]:
    """The files here that differ from the checkout, or that only one side has."""
    differing = []
    for package in PACKAGES:
        for path, data in _wanted(package, checkout).items():
            if _bytes(path) != data:
                differing.append(str(path.relative_to(ROOT)))
    return differing


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def check(checkout: Path) -> int:
    differing = behind(checkout)
    for name in differing:
        print(f"{name}: not the store's current file")
    if differing:
        print("Run the Copy tariffstore workflow and merge its pull request, then try again.")
    return 1 if differing else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"] and len(argv) == 2:
        return check(Path(argv[1]).resolve())
    if len(argv) != 1:
        print(__doc__)
        return 2
    checkout = Path(argv[0]).resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    for package in PACKAGES:
        count = copy_package(package, checkout, commit)
        print(f"{package.name}: copied {count} files from {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
