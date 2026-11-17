"""The tariff library is pinned once, in the manifest, and every test environment installs the same pin."""

from __future__ import annotations

import json

from tests.helpers import PKG, ROOT

MARKER = "utility-tariffs-lib@"
ENVIRONMENTS = ("requirements-test.txt", "requirements-test-e2e.txt", "tests/ha_e2e/requirements-floor.txt")


def _manifest_pins() -> set[str]:
    return set(json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))["requirements"])


def test_the_manifest_pins_one_archive_of_the_library() -> None:
    pins = _manifest_pins()
    assert len(pins) == 1
    (pin,) = pins
    assert pin.startswith(MARKER + "https://github.com/macuistin/utility-tariffs/archive/")


def test_every_test_environment_installs_the_manifest_pin() -> None:
    for name in ENVIRONMENTS:
        lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
        assert {line for line in lines if line.startswith(MARKER)} == _manifest_pins(), name
