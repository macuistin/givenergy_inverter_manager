"""Which GivTCP releases reset entity ids, and how a version is read."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.givtcp_version import (
    FIRST_AFFECTED_VERSION,
    FIXED_IN_VERSION,
    parse_version,
    resets_entity_ids,
)


def test_the_affected_releases_run_from_3_6_to_the_one_that_fixed_it():
    assert (FIRST_AFFECTED_VERSION, FIXED_IN_VERSION) == ("3.6", "3.6.2")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.6.3", (3, 6, 3)),
        ("v3.6.3", (3, 6, 3)),
        ("3.6.3-beta", (3, 6, 3)),
        ("3.10", (3, 10)),
        ("unknown", None),
        ("unavailable", None),
        ("", None),
        (None, None),
    ],
)
def test_a_version_is_read_from_its_leading_numbers(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["3.6", "3.6.0", "3.6.1", "v3.6.1", "3.6.1-rc1", "3.6.1.5"])
def test_3_6_and_3_6_1_reset_entity_ids(text):
    assert resets_entity_ids(text) is True


@pytest.mark.parametrize(
    "text", ["3.6.2", "3.6.3", "3.6.4", "3.7", "3.10.0", "4.0", "3.5.78", "3.5.9", "2.9.9"]
)
def test_the_fixed_release_newer_ones_and_older_ones_do_not(text):
    assert resets_entity_ids(text) is False


@pytest.mark.parametrize("text", [None, "", "unknown", "unavailable", "not a version"])
def test_a_version_nobody_can_read_raises_nothing(text):
    assert resets_entity_ids(text) is False
