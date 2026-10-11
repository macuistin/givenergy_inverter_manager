"""Packaging, CI and version metadata stay consistent with the code."""

from __future__ import annotations

import ast
import json
import re
import tomllib

import pytest
import yaml

from tests.helpers import PKG, ROOT

# Source text that needs a minimum Home Assistant release, checked against the
# released Home Assistant wheels: ConfigEntry.runtime_data first ships in 2024.6,
# config flow sections in 2024.7 and the DataUpdateCoordinator config_entry
# argument in 2024.11. The generated dashboard puts button badges on heading cards,
# which first ship in 2026.2. The floor in hacs.json is 2026.5.0, so all four hold. Add a rule
# when the code starts using an API from a newer release.
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


# 0.18.0, 0.18.0b1 or 0.18.0rc1: a beta or release candidate build states its suffix too.
_VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?"


def _version_sources() -> dict[str, str]:
    """Every place that states the release version, keyed by where it lives."""
    from custom_components.givenergy_inverter_manager.const import INTEGRATION_VERSION

    readme = re.search(rf"Current version: ({_VERSION})", (ROOT / "README.md").read_text())
    index = re.search(
        rf"This documentation matches version ({_VERSION})",
        (ROOT / "docs" / "index.md").read_text(),
    )
    requirements = re.search(
        rf"The current release is ({_VERSION})", (ROOT / "REQUIREMENTS.md").read_text()
    )
    return {
        "const.INTEGRATION_VERSION": INTEGRATION_VERSION,
        "manifest.json": json.loads((PKG / "manifest.json").read_text())["version"],
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
            "version"
        ],
        "README.md": readme.group(1) if readme else "missing 'Current version:' line",
        "docs/index.md": index.group(1) if index else "missing 'matches version' line",
        "REQUIREMENTS.md": requirements.group(1) if requirements else "missing 'current release'",
    }


def test_every_version_statement_agrees():
    sources = _version_sources()

    assert len(set(sources.values())) == 1, sources


def test_coverage_report_is_ignored():
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert "coverage.json" in ignored


_WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str = "tests.yml") -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text())


def test_check_names_are_stable():
    """Check names appear in the PR check list, so renaming a job is a deliberate change."""
    jobs = _workflow()["jobs"]

    assert set(jobs) == {"lint", "tests-python", "tests-beta", "e2e", "e2e-beta"}
    assert "name" not in jobs["lint"]
    assert jobs["tests-python"]["name"] == "Tests (Home Assistant ${{ matrix.home-assistant }})"
    assert jobs["tests-beta"]["name"] == "Tests (Home Assistant beta, not blocking)"
    assert jobs["e2e"]["name"] == "Home Assistant end-to-end (${{ matrix.home-assistant }})"
    assert jobs["e2e-beta"]["name"] == "Home Assistant end-to-end (beta, not blocking)"
    assert "name" not in _workflow("hassfest.yml")["jobs"]["validate"]
    assert _workflow("hacs.yml")["jobs"]["hacs"]["name"] == "HACS Action"
    assert _workflow("codeql.yml")["jobs"]["analyze"]["name"] == "Analyze (${{ matrix.language }})"


def test_lint_job_does_not_run_the_tests():
    steps = _workflow()["jobs"]["lint"]["steps"]

    assert not any("pytest" in step.get("run", "") for step in steps)


def test_every_workflow_has_read_only_permissions_and_cancels_superseded_pr_runs():
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())

        assert workflow["permissions"] == {"contents": "read"}, path.name
        assert workflow["concurrency"]["cancel-in-progress"] == (
            "${{ github.event_name == 'pull_request' }}"
        ), path.name


def test_python_jobs_cache_pip():
    for job in _workflow()["jobs"].values():
        setup = next(step for step in job["steps"] if "setup-python" in step.get("uses", ""))

        assert setup["with"]["cache"] == "pip"


def test_dependabot_covers_actions_and_pip_weekly():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    updates = {item["package-ecosystem"]: item for item in config["updates"]}

    assert set(updates) == {"github-actions", "pip"}
    assert all(item["schedule"]["interval"] == "weekly" for item in updates.values())


@pytest.mark.parametrize("name", ["tests.yml", "hassfest.yml", "hacs.yml"])
def test_workflow_runs_nightly(name):
    triggers = _workflow(name)[True]

    assert triggers["schedule"]
    assert all(re.fullmatch(r"(\S+ ){4}\S+", item["cron"]) for item in triggers["schedule"])


def _setup_python_versions(workflow: dict) -> set[str]:
    return {
        str(step["with"]["python-version"])
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "setup-python" in step.get("uses", "")
    }


def test_every_python_job_runs_the_python_home_assistant_needs():
    """Home Assistant 2026.5 and newer need Python 3.14.2 or newer and do not install on 3.13."""
    assert _setup_python_versions(_workflow()) == {"3.14"}


def _hacs_minimum() -> str:
    return json.loads((ROOT / "hacs.json").read_text())["homeassistant"]


def test_the_unit_and_e2e_jobs_run_on_the_hacs_minimum_and_the_latest_release():
    jobs = _workflow()["jobs"]

    for name in ("tests-python", "e2e"):
        versions = [row["home-assistant"] for row in jobs[name]["strategy"]["matrix"]["include"]]
        assert versions == [_hacs_minimum(), "latest"], name


def test_the_floor_jobs_install_the_hacs_minimum():
    jobs = _workflow()["jobs"]
    unit_floor = jobs["tests-python"]["strategy"]["matrix"]["include"][0]
    e2e_floor = jobs["e2e"]["strategy"]["matrix"]["include"][0]
    floor_file = (ROOT / e2e_floor["requirements"]).read_text().splitlines()

    assert unit_floor["pin"] == f"homeassistant=={_hacs_minimum()}"
    assert f"# pins homeassistant=={_hacs_minimum()}" in floor_file
    assert any(line.startswith("pytest-homeassistant-custom-component==") for line in floor_file)


def test_beta_jobs_do_not_block_and_the_others_do():
    jobs = _workflow()["jobs"]

    assert jobs["tests-beta"]["continue-on-error"] is True
    assert jobs["e2e-beta"]["continue-on-error"] is True
    assert not any(
        "continue-on-error" in job for name, job in jobs.items() if not name.endswith("beta")
    )


def test_the_dependabot_pip_scan_does_not_reach_the_floor_requirements():
    """Dependabot reads requirements files in the root only. It must not bump the floor pin."""
    floor_file = ROOT / "tests" / "ha_e2e" / "requirements-floor.txt"

    assert floor_file.exists()
    assert list(ROOT.glob("requirements*floor*.txt")) == []


def test_the_docs_state_the_hacs_minimum():
    for path in (ROOT / "README.md", ROOT / "docs" / "index.md", ROOT / "REQUIREMENTS.md"):
        assert _hacs_minimum() in path.read_text(), path.name


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


def _platform_source(name: str) -> str:
    """Return a platform's source, including the sensor description modules."""
    paths = [PKG / f"{name}.py"]
    if name == "sensor":
        paths += sorted((PKG / "sensor_descriptions").glob("*.py"))
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_quality_scale_done_claims_hold_in_the_code():
    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    if _quality_status("action-setup") == "done":
        assert "async def async_setup(" in init

    untranslated = [
        name
        for name in ("sensor", "switch", "number", "button")
        if "translation_key" not in _platform_source(name)
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


def test_only_the_prerelease_workflow_can_write_and_only_at_job_level():
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        writers = [
            name
            for name, job in workflow["jobs"].items()
            if (job.get("permissions") or {}).get("contents") == "write"
        ]

        assert writers == (["prerelease"] if path.name == "prerelease.yml" else []), path.name


def test_the_prerelease_workflow_publishes_beta_and_rc_tags_after_checking_the_version():
    workflow = _workflow("prerelease.yml")
    job = workflow["jobs"]["prerelease"]
    runs = [step.get("run", "") for step in job["steps"]]

    assert set(workflow[True]) == {"push"}
    assert workflow[True]["push"]["tags"] == ["v0.18.0b*", "v0.18.0rc*"]
    assert "branches" not in workflow[True]["push"]
    assert any(run.startswith('python scripts/set_version.py --check "${GITHUB_REF_NAME}"') for run in runs)
    publish = next(run for run in runs if "gh release create" in run)
    assert "--prerelease" in publish
    assert "--verify-tag" in publish
    check_index = next(i for i, run in enumerate(runs) if "set_version.py" in run)
    assert check_index < runs.index(publish)


def test_workflow_actions_are_pinned_to_a_major_version_tag_like_the_others():
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                action = step.get("uses", "")
                if action.startswith("actions/"):
                    assert re.fullmatch(r"actions/[\w-]+@v[0-9]+", action), (path.name, action)
