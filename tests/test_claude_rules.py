"""The Claude Code rules and skills stay short, well formed and true to the repo.

CLAUDE.md is read on every task, so it stays short. AGENTS.md is a symlink to it for tools that
read that name. Each rule file has frontmatter and a size cap. Every repo path the rules, skills
and CLAUDE.md name in backticks or code blocks must exist, so a renamed file cannot leave a rule
pointing at nothing. A path is skipped when it holds a glob or a placeholder, or when its line
carries the marker "(example)".
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from tests.helpers import PKG, ROOT

CLAUDE_MD = ROOT / "CLAUDE.md"
AGENTS_MD = ROOT / "AGENTS.md"
RULES = sorted((ROOT / ".claude" / "rules").glob("*.md"))
SKILLS = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))

MAX_CLAUDE_MD_LINES = 150
MAX_RULE_LINES = 80
MAX_SKILLS = 3

_PREFIXES = ("custom_components/", "tests/", "docs/", "scripts/", "tools/")
_CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)
_TOKEN = re.compile(r"[\w.\-/*<>{}]+")
_EXAMPLE_MARK = "(example)"
_EM_DASH = "—"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path.name} has no frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path.name} frontmatter is not a mapping"
    return data


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def _looks_like_repo_path(token: str) -> bool:
    if "/" not in token or token.startswith("/"):
        return False
    if any(char in token for char in "*<>{}"):
        return False
    last = token.rstrip("/").rsplit("/", 1)[-1]
    return "." in last.lstrip(".") or token.startswith(_PREFIXES)


def _named_paths(path: Path) -> Iterator[str]:
    """The repo paths a markdown file names inside code spans and fenced blocks."""
    body = _body(path)
    for match in _CODE.finditer(body):
        line_start = body.rfind("\n", 0, match.start()) + 1
        line_end = body.find("\n", match.end())
        line = body[line_start : line_end if line_end != -1 else len(body)]
        if _EXAMPLE_MARK in line:
            continue
        for token in _TOKEN.findall(match.group(0)):
            token = token.rstrip(".")
            if _looks_like_repo_path(token):
                yield token


def _exists(token: str) -> bool:
    """A path may be written from the repo root, the integration or the tests folder."""
    return any((base / token).exists() for base in (ROOT, PKG, ROOT / "tests"))


def test_claude_md_is_short():
    lines = len(CLAUDE_MD.read_text(encoding="utf-8").splitlines())

    assert lines < MAX_CLAUDE_MD_LINES


def test_agents_md_is_a_relative_symlink_to_claude_md():
    assert AGENTS_MD.is_symlink()
    assert AGENTS_MD.readlink() == Path("CLAUDE.md")
    assert AGENTS_MD.read_text(encoding="utf-8") == CLAUDE_MD.read_text(encoding="utf-8")


def test_there_are_rule_files():
    assert RULES


@pytest.mark.parametrize("path", RULES, ids=lambda path: path.name)
def test_a_rule_file_has_frontmatter_and_stays_short(path):
    frontmatter = _frontmatter(path)

    assert isinstance(frontmatter.get("description"), str)
    assert frontmatter["description"].strip()
    paths = frontmatter.get("paths", [])
    assert isinstance(paths, list)
    assert all(isinstance(pattern, str) and pattern for pattern in paths)
    assert len(path.read_text(encoding="utf-8").splitlines()) < MAX_RULE_LINES


@pytest.mark.parametrize("path", RULES, ids=lambda path: path.name)
def test_claude_md_points_at_every_rule_file(path):
    assert f".claude/rules/{path.name}" in CLAUDE_MD.read_text(encoding="utf-8")


def test_the_number_of_skills_is_capped():
    assert 0 < len(SKILLS) <= MAX_SKILLS


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_a_skill_has_a_name_that_matches_its_folder(path):
    frontmatter = _frontmatter(path)

    assert frontmatter["name"] == path.parent.name
    assert isinstance(frontmatter.get("description"), str)
    assert frontmatter["description"].strip()


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_claude_md_lists_every_skill(path):
    assert f"`/{path.parent.name}`" in CLAUDE_MD.read_text(encoding="utf-8")


_NAMING_FILES = [CLAUDE_MD, *RULES, *SKILLS]


@pytest.mark.parametrize("path", _NAMING_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_repo_path_a_rule_names_exists(path):
    missing = sorted({token for token in _named_paths(path) if not _exists(token)})

    assert missing == []


@pytest.mark.parametrize("path", _NAMING_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_the_rule_files_use_no_em_dash(path):
    assert _EM_DASH not in path.read_text(encoding="utf-8")


def test_the_path_check_finds_paths_and_skips_globs_and_examples(tmp_path):
    sample = tmp_path / "sample.md"
    sample.write_text(
        "See `tests/test_metadata.py` and `core/engine.py`.\n"
        "Skip `tests/*.py` and `chore/release-<version>`.\n"
        "A moved file `tests/old/gone.py` (example) is skipped.\n"
        "```bash\npython scripts/gen_sensor_docs.py\n```\n",
        encoding="utf-8",
    )

    assert sorted(_named_paths(sample)) == [
        "core/engine.py",
        "scripts/gen_sensor_docs.py",
        "tests/test_metadata.py",
    ]


def test_the_path_check_fails_on_a_path_that_does_not_exist():
    assert not _exists("tests/no_such_file_anywhere.py")
