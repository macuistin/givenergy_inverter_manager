"""quality_scale.yaml names every rule of the tiers the integration works towards.

The rule lists are Home Assistant's own (https://contributors.home-assistant.io/core/quality-scale/).
When Home Assistant adds a rule to a tier, add it here and to the yaml in the same change, so the
yaml never claims more than it checked.
"""

from __future__ import annotations

import yaml

from tests.helpers import PKG

BRONZE = (
    "action-setup appropriate-polling brands common-modules config-flow config-flow-test-coverage "
    "dependency-transparency docs-actions docs-conditions docs-high-level-description "
    "docs-installation-instructions docs-removal-instructions docs-triggers entity-event-setup "
    "entity-unique-id has-entity-name runtime-data test-before-configure test-before-setup "
    "unique-config-entry"
).split()
SILVER = (
    "action-exceptions config-entry-unloading docs-configuration-parameters "
    "docs-installation-parameters entity-unavailable integration-owner log-when-unavailable "
    "parallel-updates reauthentication-flow test-coverage"
).split()
GOLD = (
    "devices diagnostics discovery discovery-update-info docs-data-update docs-examples "
    "docs-known-limitations docs-supported-devices docs-supported-functions docs-troubleshooting "
    "docs-use-cases dynamic-devices entity-category entity-device-class entity-disabled-by-default "
    "entity-translations exception-translations icon-translations reconfiguration-flow "
    "repair-issues stale-devices"
).split()
PLATINUM = "async-dependency inject-websession strict-typing".split()

STATUSES = {"done", "todo", "exempt"}


def _rules() -> dict[str, dict]:
    rules = yaml.safe_load((PKG / "quality_scale.yaml").read_text())["rules"]
    return {name: value if isinstance(value, dict) else {"status": value} for name, value in rules.items()}


def test_every_rule_of_every_tier_is_listed():
    listed = set(_rules())
    missing = [r for r in BRONZE + SILVER + GOLD + PLATINUM if r not in listed]
    assert not missing, f"quality_scale.yaml is missing: {missing}"


def test_no_rule_is_listed_that_the_scale_does_not_have():
    known = set(BRONZE + SILVER + GOLD + PLATINUM)
    assert set(_rules()) <= known


def test_every_status_is_done_todo_or_exempt():
    for name, rule in _rules().items():
        assert rule["status"] in STATUSES, name


def test_every_exemption_gives_a_reason():
    for name, rule in _rules().items():
        if rule["status"] == "exempt":
            assert rule.get("comment", "").strip(), f"{name} is exempt without a reason"
