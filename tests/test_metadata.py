"""Packaging, CI and version metadata stay consistent with the code."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent.parent
_PKG = _ROOT / "custom_components" / "givenergy_inverter_manager"

# Source text that needs a minimum Home Assistant release, checked against the
# released Home Assistant wheels: ConfigEntry.runtime_data first ships in 2024.6,
# config flow sections in 2024.7 and the DataUpdateCoordinator config_entry
# argument in 2024.11.
_HA_FLOOR_RULES = (
    ("runtime_data", (2024, 6, 0)),
    ("section(", (2024, 7, 0)),
    ("config_entry=entry", (2024, 11, 0)),
)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_hacs_minimum_covers_the_apis_the_code_uses():
    source = "\n".join(path.read_text(encoding="utf-8") for path in _PKG.rglob("*.py"))
    needed = max(floor for needle, floor in _HA_FLOOR_RULES if needle in source)
    declared = _version(json.loads((_ROOT / "hacs.json").read_text())["homeassistant"])

    assert declared >= needed


def test_requirements_floor_matches_hacs_minimum():
    hacs = json.loads((_ROOT / "hacs.json").read_text())["homeassistant"]
    text = (_ROOT / "requirements-test.txt").read_text()

    assert f"homeassistant>={hacs}" in text.splitlines()


def test_test_requirements_have_upper_bounds():
    lines = [
        line
        for line in (_ROOT / "requirements-test.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    unbounded = [
        line for line in lines if not line.startswith("homeassistant") and "<" not in line
    ]

    assert unbounded == []


def test_pyproject_build_backend_exists():
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text())

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"


def test_pyproject_version_matches_manifest():
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    manifest = json.loads((_PKG / "manifest.json").read_text())

    assert pyproject["project"]["version"] == manifest["version"]


def test_coverage_report_is_ignored():
    ignored = (_ROOT / ".gitignore").read_text().splitlines()

    assert "coverage.json" in ignored


def _workflow() -> dict:
    return yaml.safe_load((_ROOT / ".github" / "workflows" / "tests.yml").read_text())


def test_required_job_names_are_unchanged():
    jobs = _workflow()["jobs"]

    assert "name" not in jobs["tests"]
    assert jobs["e2e"]["name"] == "Home Assistant end-to-end"


def test_workflow_runs_nightly():
    triggers = _workflow()[True]

    assert triggers["schedule"]
    assert all(re.fullmatch(r"(\S+ ){4}\S+", item["cron"]) for item in triggers["schedule"])


def test_newer_python_versions_are_tested():
    job = _workflow()["jobs"]["tests-python"]

    assert job["strategy"]["matrix"]["python-version"] == ["3.13", "3.14"]


def test_every_platform_sets_parallel_updates():
    import ast

    missing = []
    for name in ("sensor", "switch", "number", "button"):
        tree = ast.parse((_PKG / f"{name}.py").read_text(encoding="utf-8"))
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        if "PARALLEL_UPDATES" not in assigned:
            missing.append(name)

    assert missing == []


def _quality_status(rule: str) -> str:
    rules = yaml.safe_load((_PKG / "quality_scale.yaml").read_text())["rules"]
    value = rules[rule]
    return value if isinstance(value, str) else value["status"]


def test_quality_scale_uses_known_statuses_and_explains_exemptions():
    rules = yaml.safe_load((_PKG / "quality_scale.yaml").read_text())["rules"]

    for name, value in rules.items():
        status = value if isinstance(value, str) else value["status"]
        assert status in {"done", "todo", "exempt"}, name
        if status == "exempt":
            assert value["comment"], name


def test_quality_scale_done_claims_hold_in_the_code():
    init = (_PKG / "__init__.py").read_text(encoding="utf-8")
    if _quality_status("action-setup") == "done":
        assert "async def async_setup(" in init

    untranslated = [
        name
        for name in ("sensor", "switch", "number", "button")
        if "translation_key" not in (_PKG / f"{name}.py").read_text(encoding="utf-8")
    ]
    for rule in ("entity-translations", "icon-translations"):
        if _quality_status(rule) == "done":
            assert untranslated == [], rule

    if _quality_status("strict-typing") == "done":
        assert (_PKG / "py.typed").exists()
