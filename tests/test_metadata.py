"""Packaging, CI and version metadata stay consistent with the code."""

from __future__ import annotations

import ast
import json
import re
import tomllib

import yaml

from tests.helpers import PKG, ROOT

# Source text that needs a minimum Home Assistant release, checked against the
# released Home Assistant wheels: ConfigEntry.runtime_data first ships in 2024.6,
# config flow sections in 2024.7 and the DataUpdateCoordinator config_entry
# argument in 2024.11. The generated dashboard puts button badges on heading cards,
# which first ship in 2026.2.
_HA_FLOOR_RULES = (
    ("runtime_data", (2024, 6, 0)),
    ("section(", (2024, 7, 0)),
    ("config_entry=entry", (2024, 11, 0)),
    ('card["badges"]', (2026, 2, 0)),
)


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_hacs_minimum_covers_the_apis_the_code_uses():
    source = "\n".join(path.read_text(encoding="utf-8") for path in PKG.rglob("*.py"))
    needed = max(floor for needle, floor in _HA_FLOOR_RULES if needle in source)
    declared = _version(json.loads((ROOT / "hacs.json").read_text())["homeassistant"])

    assert declared >= needed


def test_requirements_floor_matches_hacs_minimum():
    hacs = json.loads((ROOT / "hacs.json").read_text())["homeassistant"]
    text = (ROOT / "requirements-test.txt").read_text()

    assert f"homeassistant>={hacs}" in text.splitlines()


def test_test_requirements_have_upper_bounds():
    lines = [
        line
        for line in (ROOT / "requirements-test.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    unbounded = [
        line for line in lines if not line.startswith("homeassistant") and "<" not in line
    ]

    assert unbounded == []


def test_pyproject_build_backend_exists():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"


def _version_sources() -> dict[str, str]:
    """Every place that states the release version, keyed by where it lives."""
    from custom_components.givenergy_inverter_manager.const import INTEGRATION_VERSION

    readme = re.search(
        r"Current version: ([0-9]+(?:\.[0-9]+)*)", (ROOT / "README.md").read_text()
    )
    index = re.search(
        r"This documentation matches version ([0-9]+(?:\.[0-9]+)*)",
        (ROOT / "docs" / "index.md").read_text(),
    )
    return {
        "const.INTEGRATION_VERSION": INTEGRATION_VERSION,
        "manifest.json": json.loads((PKG / "manifest.json").read_text())["version"],
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
            "version"
        ],
        "README.md": readme.group(1) if readme else "missing 'Current version:' line",
        "docs/index.md": index.group(1) if index else "missing 'matches version' line",
    }


def test_every_version_statement_agrees():
    sources = _version_sources()

    assert len(set(sources.values())) == 1, sources


def test_coverage_report_is_ignored():
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert "coverage.json" in ignored


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text())


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
        tree = ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))
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
    rules = yaml.safe_load((PKG / "quality_scale.yaml").read_text())["rules"]
    value = rules[rule]
    return value if isinstance(value, str) else value["status"]


def test_quality_scale_uses_known_statuses_and_explains_exemptions():
    rules = yaml.safe_load((PKG / "quality_scale.yaml").read_text())["rules"]

    for name, value in rules.items():
        status = value if isinstance(value, str) else value["status"]
        assert status in {"done", "todo", "exempt"}, name
        if status == "exempt":
            assert value["comment"], name


def test_quality_scale_done_claims_hold_in_the_code():
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    if _quality_status("action-setup") == "done":
        assert "async def async_setup(" in init

    untranslated = [
        name
        for name in ("sensor", "switch", "number", "button")
        if "translation_key" not in (PKG / f"{name}.py").read_text(encoding="utf-8")
    ]
    for rule in ("entity-translations", "icon-translations"):
        if _quality_status(rule) == "done":
            assert untranslated == [], rule

    if _quality_status("strict-typing") == "done":
        assert (PKG / "py.typed").exists()


def test_device_manufacturer_is_not_givenergy():
    """GivEnergy makes the inverter, not this integration, so no platform may claim it."""
    for path in PKG.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert '"manufacturer": "GivEnergy"' not in text, path.name
    const = (PKG / "const.py").read_text(encoding="utf-8")
    assert 'DEVICE_MANUFACTURER = "macuistin"' in const


def test_core_package_does_not_import_home_assistant():
    """core/ is pure Python so it stays testable without Home Assistant."""
    offenders = []
    for path in sorted((PKG / "core").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] == "homeassistant"]

    assert offenders == []
