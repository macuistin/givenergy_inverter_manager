"""The tariffstore folder is a copy: every file matches what UPSTREAM.json says was copied."""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from scripts import copy_tariffstore
from tests.helpers import PKG

FOLDER = PKG / "lib" / "tariffstore"


def _upstream() -> dict:
    return json.loads((FOLDER / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_every_copied_file_matches_its_recorded_hash():
    recorded = _upstream()["files"]
    on_disk = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in FOLDER.glob("*.py")}

    assert on_disk == recorded, "edit lib/tariffstore in the store repository, then copy it again"


def test_the_record_names_the_commit_it_was_copied_from():
    upstream = _upstream()

    assert upstream["repository"] == "macuistin/utility-tariffs"
    assert len(upstream["commit"]) == 40


def _git(checkout, *command):
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run(["git", *identity, *command], cwd=checkout, check=True)


def test_the_copy_script_replaces_the_files_and_records_them(tmp_path, monkeypatch):
    checkout = tmp_path / "store"
    (checkout / "lib" / "tariffstore").mkdir(parents=True)
    (checkout / "tests").mkdir()
    (checkout / "lib" / "tariffstore" / "client.py").write_text("NEW = 1\n")
    for name in copy_tariffstore.COPIED_TESTS:
        (checkout / "tests" / name).write_text(
            "from lib.tariffstore import Store\nfrom scripts import build\n"
            "from tests.fixtures import tariff\n"
        )
    _git(checkout, "init", "-q")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "x")
    target, tests = tmp_path / "target", tmp_path / "tests"
    target.mkdir()
    tests.mkdir()
    (target / "gone.py").write_text("OLD = 1\n")
    monkeypatch.setattr(copy_tariffstore, "TARGET", target)
    monkeypatch.setattr(copy_tariffstore, "TESTS", tests)

    assert copy_tariffstore.main([str(checkout)]) == 0

    assert sorted(p.name for p in target.iterdir()) == ["UPSTREAM.json", "client.py"]
    record = json.loads((target / "UPSTREAM.json").read_text())
    assert record["files"] == {"client.py": hashlib.sha256(b"NEW = 1\n").hexdigest()}
    assert len(record["commit"]) == 40
    assert (tests / "test_client.py").read_text() == (
        copy_tariffstore.HEADER
        + "from custom_components.givenergy_inverter_manager.lib.tariffstore import Store\n"
        "from .building import build_store\nfrom .fixtures import tariff\n"
    )


def test_the_copy_script_explains_itself_without_a_path(capsys: pytest.CaptureFixture[str]):
    assert copy_tariffstore.main([]) == 2
    assert "copy_tariffstore.py" in capsys.readouterr().out
