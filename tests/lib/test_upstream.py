"""The tariff libraries are copies: every file matches what its UPSTREAM.json says was copied."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import copy_tariffstore
from tests.helpers import PKG

COPIED = [package.name for package in copy_tariffstore.PACKAGES]
CLIENT_TEST = (
    "from lib.tariffstore import Store\nfrom scripts import build\n"
    "from tests.fixtures import tariff\n"
)
ENGINE_TEST = "from lib.tariff import money\nfrom tests.tariff.example import document\n"


def _upstream(name: str) -> dict:
    return json.loads((PKG / "lib" / name / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_the_engine_its_clock_helpers_and_the_store_client_are_the_copied_packages():
    assert sorted(COPIED) == ["tariff", "tariffstore", "timeutil"]


@pytest.mark.parametrize("name", COPIED)
def test_every_copied_file_matches_its_recorded_hash(name):
    recorded = _upstream(name)["files"]
    folder = PKG / "lib" / name
    on_disk = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.iterdir()
        if p.suffix == ".py" or p.name in recorded
    }

    assert on_disk == recorded, f"edit lib/{name} in the store repository, then copy it again"


@pytest.mark.parametrize("name", COPIED)
def test_the_record_names_the_commit_it_was_copied_from(name):
    upstream = _upstream(name)

    assert upstream["repository"] == "macuistin/utility-tariffs"
    assert upstream["path"] == f"lib/{name}"
    assert len(upstream["commit"]) == 40


def test_all_three_packages_were_copied_from_one_commit():
    assert len({_upstream(name)["commit"] for name in COPIED}) == 1


def _git(checkout, *command):
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run(["git", *identity, *command], cwd=checkout, check=True)


def _store(tmp_path: Path) -> Path:
    """A checkout shaped like the store, with one module and one test for each package."""
    checkout = tmp_path / "store"
    for name in COPIED:
        (checkout / "lib" / name).mkdir(parents=True)
        (checkout / "lib" / name / "module.py").write_text("NEW = 1\n")
    (checkout / "lib" / "tariff" / "README.md").write_text("# tariff\n")
    for folder in ("tariff", "timeutil"):
        (checkout / "tests" / folder).mkdir(parents=True)
        (checkout / "tests" / folder / "__init__.py").write_text("")
        (checkout / "tests" / folder / "test_it.py").write_text(ENGINE_TEST)
    for name in copy_tariffstore.CLIENT_TESTS:
        (checkout / "tests" / name).write_text(CLIENT_TEST)
    _git(checkout, "init", "-q")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "x")
    return checkout


@pytest.fixture
def here(tmp_path, monkeypatch) -> Path:
    """An empty repository root for the script to copy into."""
    root = tmp_path / "here"
    monkeypatch.setattr(copy_tariffstore, "ROOT", root)
    monkeypatch.setattr(copy_tariffstore, "LIB", root / "lib")
    monkeypatch.setattr(copy_tariffstore, "TESTS", root / "tests")
    return root


def test_the_copy_script_replaces_the_files_and_records_them(tmp_path, here):
    checkout = _store(tmp_path)
    (here / "lib" / "tariff").mkdir(parents=True)
    (here / "lib" / "tariff" / "gone.py").write_text("OLD = 1\n")

    assert copy_tariffstore.main([str(checkout)]) == 0

    engine = here / "lib" / "tariff"
    assert sorted(p.name for p in engine.iterdir()) == ["README.md", "UPSTREAM.json", "module.py"]
    record = json.loads((engine / "UPSTREAM.json").read_text())
    assert record["files"] == {
        "README.md": hashlib.sha256(b"# tariff\n").hexdigest(),
        "module.py": hashlib.sha256(b"NEW = 1\n").hexdigest(),
    }
    assert len(record["commit"]) == 40
    for name in ("timeutil", "tariffstore"):
        assert (here / "lib" / name / "module.py").read_text() == "NEW = 1\n"


def test_copied_tests_have_their_imports_pointed_at_the_copy(tmp_path, here):
    assert copy_tariffstore.main([str(_store(tmp_path))]) == 0

    lib = "custom_components.givenergy_inverter_manager.lib"
    assert (here / "tests" / "tariffstore" / "test_client.py").read_text() == (
        copy_tariffstore.HEADER
        + f"from {lib}.tariffstore import Store\n"
        "from .building import build_store\nfrom .fixtures import tariff\n"
    )
    assert (here / "tests" / "tariff" / "test_it.py").read_text() == (
        copy_tariffstore.HEADER
        + f"from {lib}.tariff import money\nfrom tests.lib.tariff.example import document\n"
    )
    assert not (here / "tests" / "tariff" / "__init__.py").exists()


def test_check_passes_on_a_fresh_copy_and_names_a_file_that_fell_behind(
    tmp_path, here, capsys: pytest.CaptureFixture[str]
):
    checkout = _store(tmp_path)
    assert copy_tariffstore.main([str(checkout)]) == 0

    assert copy_tariffstore.main(["--check", str(checkout)]) == 0

    (checkout / "lib" / "tariff" / "module.py").write_text("NEW = 2\n")
    (checkout / "lib" / "timeutil" / "added.py").write_text("X = 1\n")
    (here / "lib" / "tariffstore" / "stale.py").write_text("OLD = 1\n")
    (checkout / "tests" / "tariff" / "test_more.py").write_text("from lib.tariff import money\n")
    (checkout / "tests" / "test_index.py").write_text("from lib.tariffstore import index\n")
    capsys.readouterr()

    assert copy_tariffstore.main(["--check", str(checkout)]) == 1

    lines = capsys.readouterr().out.splitlines()
    assert lines[:-1] == [
        "lib/tariff/module.py: not the store's current file",
        "tests/tariff/test_more.py: not the store's current file",
        "lib/timeutil/added.py: not the store's current file",
        "lib/tariffstore/stale.py: not the store's current file",
        "tests/tariffstore/test_index.py: not the store's current file",
    ]
    assert "Copy tariffstore" in lines[-1]
    assert (here / "lib" / "tariff" / "module.py").read_text() == "NEW = 1\n"  # nothing written


def test_the_copy_script_explains_itself_without_a_path(capsys: pytest.CaptureFixture[str]):
    assert copy_tariffstore.main([]) == 2
    assert "copy_tariffstore.py" in capsys.readouterr().out
