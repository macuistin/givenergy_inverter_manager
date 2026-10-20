"""scripts/set_version.py writes and checks the version in all six places, and reads the notes."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from tests.helpers import ROOT

_SPEC = importlib.util.spec_from_file_location("set_version", ROOT / "scripts" / "set_version.py")
set_version = importlib.util.module_from_spec(_SPEC)
sys.modules["set_version"] = set_version
_SPEC.loader.exec_module(set_version)

PLACE_PATHS = [place.path for place in set_version.PLACES]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the six files, at the paths the script reads."""
    for relative in PLACE_PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)
    return tmp_path


def _current() -> str:
    versions = set(set_version.read_versions(ROOT).values())
    assert len(versions) == 1, versions
    return versions.pop()


@pytest.mark.parametrize(
    ("given", "version"),
    [
        ("0.18.0", "0.18.0"),
        ("v0.18.0", "0.18.0"),
        ("0.18.0b1", "0.18.0b1"),
        ("v0.18.0b1", "0.18.0b1"),
        ("v0.18.0rc2", "0.18.0rc2"),
        ("v0.18.0a3", "0.18.0a3"),
        ("v10.2.30", "10.2.30"),
    ],
)
def test_a_version_or_a_tag_normalises_to_the_version(given, version):
    assert set_version.normalise(given) == version


@pytest.mark.parametrize(
    "given",
    ["", "v", "0.18", "latest", "v0.18.0-beta.1", "0.18.0.dev1", "0.18.0b", "vv0.18.0", "0.18.0 b1"],
)
def test_anything_else_is_refused(given):
    with pytest.raises(set_version.VersionError):
        set_version.normalise(given)


def test_the_tag_for_a_version_has_the_v_prefix():
    assert set_version.tag_for("0.18.0b1") == "v0.18.0b1"


def test_every_place_in_the_repository_states_one_version():
    versions = set_version.read_versions(ROOT)

    assert len(versions) == 6
    assert None not in versions.values()
    assert len(set(versions.values())) == 1


@pytest.mark.parametrize("version", ["0.18.0b1", "0.18.0rc2", "0.18.0", "1.0.0"])
def test_writing_sets_all_six_places(tree, version):
    assert set_version.main([f"v{version}"], root=tree) == 0

    assert set(set_version.read_versions(tree).values()) == {version}


def test_writing_changes_only_the_version(tree):
    old = _current()

    set_version.main(["0.18.0b1"], root=tree)

    for relative in PLACE_PATHS:
        before = (ROOT / relative).read_text(encoding="utf-8")
        after = (tree / relative).read_text(encoding="utf-8")
        assert after == before.replace(old, "0.18.0b1", 1), relative


def test_writing_again_with_the_same_version_changes_nothing(tree):
    set_version.main(["0.18.0b1"], root=tree)
    first = {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS}

    assert set_version.main(["0.18.0b1"], root=tree) == 0

    assert {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS} == first


def test_a_missing_place_writes_nothing(tree, capsys):
    readme = tree / "README.md"
    readme.write_text(readme.read_text().replace("Current version", "Latest"), encoding="utf-8")
    before = {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS}

    assert set_version.main(["0.18.0b1"], root=tree) == 1

    assert {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS} == before
    assert "README.md: no version found" in capsys.readouterr().err


def test_check_passes_for_the_tag_that_was_written(tree):
    set_version.main(["0.18.0b1"], root=tree)

    assert set_version.main(["--check", "v0.18.0b1"], root=tree) == 0
    assert set_version.main(["--check", "0.18.0b1"], root=tree) == 0


def test_check_fails_for_a_different_tag_and_names_every_place(tree, capsys):
    set_version.main(["0.18.0b1"], root=tree)

    assert set_version.main(["--check", "v0.18.0b2"], root=tree) == 1

    err = capsys.readouterr().err
    for place in set_version.PLACES:
        assert f"{place.name}: 0.18.0b1, expected 0.18.0b2" in err


def test_check_fails_when_one_place_is_left_behind(tree, capsys):
    set_version.main(["0.18.0b1"], root=tree)
    docs = tree / "docs" / "index.md"
    docs.write_text(docs.read_text().replace("0.18.0b1", "0.17.1"), encoding="utf-8")

    assert set_version.main(["--check", "v0.18.0b1"], root=tree) == 1
    assert "docs/index.md: 0.17.1, expected 0.18.0b1" in capsys.readouterr().err
    assert set_version.main(["--check"], root=tree) == 1


def test_check_without_a_tag_passes_when_the_places_agree(tree):
    assert set_version.main(["--check"], root=tree) == 0


def test_check_refuses_a_tag_that_is_not_a_version(tree, capsys):
    assert set_version.main(["--check", "release-1"], root=tree) == 2
    assert "is not a version" in capsys.readouterr().err


def test_writing_refuses_a_version_that_is_not_one(tree):
    before = {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS}

    assert set_version.main(["0.18"], root=tree) == 2

    assert {relative: (tree / relative).read_bytes() for relative in PLACE_PATHS} == before


def test_tag_prints_the_tag_for_the_version_in_the_files(tree, capsys):
    set_version.main(["0.18.0rc1"], root=tree)
    capsys.readouterr()

    assert set_version.main(["--tag"], root=tree) == 0
    assert capsys.readouterr().out.strip() == "v0.18.0rc1"


def test_the_repository_matches_its_own_tag():
    assert set_version.main(["--check", f"v{_current()}"]) == 0


@pytest.fixture
def changelog(tree):
    path = tree / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n\n## Unreleased\n\n**Added**\n- Next.\n\n"
        "## v0.18.0\n\nShipped.\n\n## v0.17.0\n\nOlder.\n",
        encoding="utf-8",
    )
    return tree


def test_notes_are_the_versions_changelog_section(changelog, capsys):
    assert set_version.main(["--notes", "v0.18.0"], root=changelog) == 0

    assert capsys.readouterr().out.strip() == "Shipped."


def test_a_final_release_without_a_section_has_no_notes(changelog, capsys):
    assert set_version.main(["--notes", "v0.19.0"], root=changelog) == 1

    assert "no section for v0.19.0" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["v0.19.0b1", "v0.19.0rc1", "v0.19.0a1"])
def test_a_pre_release_without_a_section_uses_the_unreleased_one(changelog, capsys, version):
    assert set_version.main(["--notes", version], root=changelog) == 0

    assert "- Next." in capsys.readouterr().out


def test_a_pre_release_prefers_its_own_section(changelog, capsys):
    path = changelog / "CHANGELOG.md"
    path.write_text(path.read_text().replace("## v0.18.0\n", "## v0.18.0b1\n\nBeta.\n\n## v0.18.0\n"))

    assert set_version.main(["--notes", "v0.18.0b1"], root=changelog) == 0

    assert capsys.readouterr().out.strip() == "Beta."


def test_an_empty_unreleased_section_is_not_notes(changelog):
    path = changelog / "CHANGELOG.md"
    path.write_text(path.read_text().replace("**Added**\n- Next.\n\n", ""))

    assert set_version.main(["--notes", "v0.19.0b1"], root=changelog) == 1


def test_notes_need_a_version(changelog):
    assert set_version.main(["--notes"], root=changelog) == 2
