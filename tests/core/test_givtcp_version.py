"""The oldest GivTCP release the integration is safe on, and how a version is read."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.givtcp_version import (
    MINIMUM_GIVTCP_VERSION,
    is_older_than_minimum,
    parse_version,
)


def test_the_minimum_is_the_release_that_fixed_the_entity_id_reset():
    assert MINIMUM_GIVTCP_VERSION == "3.6.2"


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


@pytest.mark.parametrize("text", ["3.5.9", "3.6", "3.6.0", "3.6.1", "v3.6.1", "2.9.9", "3.6.1-rc1"])
def test_older_releases_are_older(text):
    assert is_older_than_minimum(text) is True


@pytest.mark.parametrize("text", ["3.6.2", "3.6.3", "3.6.4", "3.7", "3.10.0", "4.0", "3.6.2.1"])
def test_the_minimum_and_newer_are_not_older(text):
    assert is_older_than_minimum(text) is False


@pytest.mark.parametrize("text", [None, "", "unknown", "unavailable", "not a version"])
def test_a_version_nobody_can_read_raises_nothing(text):
    assert is_older_than_minimum(text) is False
