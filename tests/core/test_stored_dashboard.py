"""Which dashboard update_dashboard writes, whether it may, and what the out-of-date repair does."""

from __future__ import annotations

import json

import pytest

from custom_components.givenergy_inverter_manager.core.stored_dashboard import (
    DashboardFacts,
    DashboardRefused,
    IssueAction,
    Refusal,
    as_stored,
    choose_url_path,
    configs_match,
    ensure_writable,
    issue_action,
)
from tests.helpers import PKG

GENERATED = {"views": [{"path": "now", "sections": [{"type": "grid", "cards": []}]}]}
STORAGE = DashboardFacts(exists=True, storage_mode=True, config=GENERATED)


class TestChooseUrlPath:
    def test_the_url_path_given_wins_over_the_one_remembered(self):
        assert choose_url_path("energy-new", "energy-old") == "energy-new"

    def test_with_none_given_the_remembered_one_is_used(self):
        assert choose_url_path(None, "energy-old") == "energy-old"

    @pytest.mark.parametrize("given", ["", "   "])
    def test_a_blank_url_path_counts_as_none_given(self, given):
        assert choose_url_path(given, "energy-old") == "energy-old"

    def test_a_leading_slash_and_spaces_are_dropped(self):
        assert choose_url_path(" /energy-new ", None) == "energy-new"

    @pytest.mark.parametrize("remembered", [None, ""])
    def test_with_nothing_given_or_remembered_the_call_is_refused(self, remembered):
        with pytest.raises(DashboardRefused) as err:
            choose_url_path(None, remembered)
        assert err.value.refusal is Refusal.NO_URL_PATH


class TestEnsureWritable:
    def test_a_storage_dashboard_is_writable(self):
        ensure_writable("energy", STORAGE, recovery_mode=False)

    def test_a_new_dashboard_with_no_config_yet_is_writable(self):
        ensure_writable(
            "energy", DashboardFacts(exists=True, storage_mode=True), recovery_mode=False
        )

    def test_a_missing_dashboard_is_refused_with_its_url_path(self):
        with pytest.raises(DashboardRefused) as err:
            ensure_writable("energy", DashboardFacts(exists=False), recovery_mode=False)
        assert err.value.refusal is Refusal.NOT_FOUND
        assert err.value.url_path == "energy"

    def test_a_yaml_dashboard_is_refused(self):
        with pytest.raises(DashboardRefused) as err:
            ensure_writable("energy", DashboardFacts(exists=True), recovery_mode=False)
        assert err.value.refusal is Refusal.NOT_STORAGE

    def test_recovery_mode_refuses_even_a_storage_dashboard(self):
        with pytest.raises(DashboardRefused) as err:
            ensure_writable("energy", STORAGE, recovery_mode=True)
        assert err.value.refusal is Refusal.RECOVERY_MODE

    def test_every_refusal_is_an_exception_key_in_the_strings(self):
        exceptions = json.loads((PKG / "strings.json").read_text(encoding="utf-8"))["exceptions"]
        assert {refusal.value for refusal in Refusal} <= set(exceptions)


class TestConfigsMatch:
    def test_the_same_config_matches(self):
        assert configs_match(as_stored(GENERATED), GENERATED)

    def test_a_tuple_matches_the_list_storage_reads_back(self):
        assert configs_match({"views": [{"cards": [1, 2]}]}, {"views": [{"cards": (1, 2)}]})

    def test_a_dashboard_with_no_config_does_not_match(self):
        assert not configs_match(None, GENERATED)

    def test_an_edited_dashboard_does_not_match(self):
        edited = {"views": [*GENERATED["views"], {"path": "mine", "sections": []}]}
        assert not configs_match(edited, GENERATED)

    def test_the_order_of_views_matters(self):
        two = {"views": [{"path": "a"}, {"path": "b"}]}
        assert not configs_match({"views": [{"path": "b"}, {"path": "a"}]}, two)


class TestIssueAction:
    def test_nothing_remembered_clears_the_repair(self):
        assert issue_action("", DashboardFacts(exists=False), GENERATED) is IssueAction.CLEAR
        assert issue_action(None, STORAGE, GENERATED) is IssueAction.CLEAR

    def test_a_dashboard_that_matches_clears_the_repair(self):
        assert issue_action("energy", STORAGE, GENERATED) is IssueAction.CLEAR

    def test_a_dashboard_that_differs_raises_the_repair(self):
        changed = DashboardFacts(exists=True, storage_mode=True, config={"views": []})
        assert issue_action("energy", changed, GENERATED) is IssueAction.RAISE

    def test_a_dashboard_whose_config_was_cleared_raises_the_repair(self):
        cleared = DashboardFacts(exists=True, storage_mode=True)
        assert issue_action("energy", cleared, GENERATED) is IssueAction.RAISE

    def test_a_dashboard_that_is_gone_is_forgotten(self):
        assert issue_action("energy", DashboardFacts(exists=False), GENERATED) is (
            IssueAction.FORGET
        )

    def test_a_dashboard_that_is_now_yaml_is_forgotten(self):
        assert issue_action("energy", DashboardFacts(exists=True), GENERATED) is (
            IssueAction.FORGET
        )
