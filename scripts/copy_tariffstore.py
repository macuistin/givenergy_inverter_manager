"""Copy lib/tariffstore and its tests from a checkout of the tariff store.

    python scripts/copy_tariffstore.py ../utility-tariffs

The folder in this repository is never edited by hand. This writes the library files as they
stand at the checkout's HEAD commit and rewrites UPSTREAM.json, which
tests/lib/tariffstore/test_upstream.py checks the files against. It also writes the store's own
tests of the library, with their imports pointed at the copy, so a change there is tested here.
`.github/workflows/tariffstore-copy.yml` runs this weekly and opens a pull request.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "custom_components" / "givenergy_inverter_manager" / "lib" / "tariffstore"
TESTS = ROOT / "tests" / "lib" / "tariffstore"
SOURCE_PATH = "lib/tariffstore"
COPIED_TESTS = (
    "fixtures.py",
    "test_client.py",
    "test_compile.py",
    "test_index.py",
    "test_schema.py",
)
HEADER = "# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.\n"
# The store's tests build a store on disk with its build script. Here `building.py` does it.
REWRITES = (
    ("from lib.tariffstore", "from custom_components.givenergy_inverter_manager.lib.tariffstore"),
    ("from tests.fixtures import", "from .fixtures import"),
    ("from scripts import build\n", "from .building import build_store\n"),
    ("self.assertEqual(build.main([], self.tariffs), 0)", "build_store(self.tariffs)"),
)


def ported(text: str) -> str:
    """A test file of the store, with its imports pointed at the copy."""
    for old, new in REWRITES:
        text = text.replace(old, new)
    return HEADER + text


def copy_library(source: Path, target: Path) -> dict[str, str]:
    """Replace the library files in target with source's. Returns {file name: SHA-256}."""
    for old in target.glob("*.py"):
        old.unlink()
    files = {}
    for path in sorted(source.glob("*.py")):
        data = path.read_bytes()
        (target / path.name).write_bytes(data)
        files[path.name] = hashlib.sha256(data).hexdigest()
    return files


def copy_tests(source: Path, target: Path) -> None:
    for name in COPIED_TESTS:
        text = (source / name).read_text(encoding="utf-8")
        (target / name).write_text(ported(text), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    checkout = Path(argv[0]).resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    files = copy_library(checkout / SOURCE_PATH, TARGET)
    copy_tests(checkout / "tests", TESTS)
    upstream = {
        "repository": "macuistin/utility-tariffs",
        "path": SOURCE_PATH,
        "commit": commit,
        "files": files,
    }
    (TARGET / "UPSTREAM.json").write_text(json.dumps(upstream, indent=2) + "\n", encoding="utf-8")
    print(f"copied {len(files)} files from {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
