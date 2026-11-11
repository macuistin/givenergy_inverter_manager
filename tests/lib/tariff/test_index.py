# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The tariff index: built from files, read back, and used to load the revision in force."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import DefinitionError
from custom_components.givenergy_inverter_manager.lib.tariff.index import (
    ChecksumMismatch,
    StaticSource,
    build_index,
    canonical_json,
    checksum_of,
    find_tariff,
    load_revision,
    parse_index,
    revision_in_force,
)
from tests.lib.tariff.example_definition import example_document

TODAY = date(2026, 11, 4)
PATH1 = "ie/example-energy/example-nightboost/1.json"
PATH2 = "ie/example-energy/example-nightboost/2.json"


def doc(revision: int, start: str, end: str | None, **changes: Any) -> dict[str, Any]:
    d = example_document()
    d.update(revision=revision, effective_from=start, effective_to=end)
    d["supersedes"] = revision - 1 if revision > 1 else None
    d.update(changes)
    return d


def two_revisions() -> dict[str, str]:
    return {
        PATH1: json.dumps(doc(1, "2025-01-01", "2026-01-01")),
        PATH2: json.dumps(doc(2, "2026-01-01", None)),
    }


def test_canonical_form_ignores_key_order_and_spacing() -> None:
    assert canonical_json('{"b": 1, "a": {"d": "x", "c": "y"}}') == '{"a":{"c":"y","d":"x"},"b":1}'
    one = json.dumps(example_document(), indent=4)
    two = json.dumps(dict(reversed(example_document().items())))
    assert checksum_of(one) == checksum_of(two)
    assert checksum_of(one).startswith("sha256:") and len(checksum_of(one)) == 71


def test_build_groups_by_country_provider_and_tariff() -> None:
    built = build_index(two_revisions(), TODAY)
    tariff = built["countries"]["IE"]["providers"]["example-energy"]["tariffs"]["example-nightboost"]
    assert built["generated"] == "2026-11-04" and tariff["latest"] == 2
    assert list(tariff["revisions"]) == ["2", "1"]
    assert tariff["revisions"]["1"]["effective_to"] == "2026-01-01"
    assert tariff["revisions"]["2"]["path"] == PATH2
    assert tariff["revisions"]["2"]["checksum"] == checksum_of(two_revisions()[PATH2])
    assert tariff["completeness"] == "complete" and tariff["region"] is None


def test_an_upcoming_revision_is_not_latest() -> None:
    files = {
        PATH1: json.dumps(doc(1, "2025-01-01", "2027-01-01")),
        PATH2: json.dumps(doc(2, "2027-01-01", None)),
    }
    built = build_index(files, TODAY)
    tariff = built["countries"]["IE"]["providers"]["example-energy"]["tariffs"]["example-nightboost"]
    assert tariff["latest"] == 1
    only_future = {PATH2: json.dumps(doc(2, "2027-01-01", None, supersedes=None))}
    tariff = build_index(only_future, TODAY)["countries"]["IE"]["providers"]["example-energy"][
        "tariffs"
    ]["example-nightboost"]
    assert tariff["latest"] is None


def test_build_is_stable() -> None:
    assert build_index(two_revisions(), TODAY) == build_index(dict(reversed(two_revisions().items())), TODAY)


@pytest.mark.parametrize(
    ("files", "where", "text"),
    [
        ({"x.json": json.dumps(doc(1, "2025-01-01", None))}, "x.json", "belongs at"),
        ({PATH1: "{"}, PATH1, "not valid JSON"),
        ({PATH1: json.dumps({**doc(1, "2025-01-01", None), "extra": 1})}, PATH1, "extra"),
        (
            {
                PATH1: json.dumps(doc(1, "2025-01-01", "2026-06-01")),
                PATH2: json.dumps(doc(2, "2026-01-01", None)),
            },
            PATH2,
            "overlaps",
        ),
        (
            {
                PATH1: json.dumps(doc(1, "2025-01-01", None)),
                PATH2: json.dumps(doc(2, "2026-01-01", None)),
            },
            PATH2,
            "overlaps",
        ),
        ({PATH2: json.dumps(doc(2, "2026-01-01", None))}, PATH2, "not here"),
    ],
)
def test_build_refuses_a_set_that_disagrees(files: dict[str, str], where: str, text: str) -> None:
    with pytest.raises(DefinitionError) as err:
        build_index(files, TODAY)
    assert err.value.path == where and text in str(err.value)


def test_read_back_and_choose_by_date() -> None:
    index = parse_index(json.dumps(build_index(two_revisions(), TODAY)))
    tariff = find_tariff(index, "IE", "example-energy", "example-nightboost")
    assert index.generated == TODAY and tariff.latest == 2 and tariff.complete
    assert index.countries["IE"]["example-energy"].name == "Example Energy"
    old = revision_in_force(tariff, date(2025, 12, 31))
    assert old is not None and old.revision == 1
    new = revision_in_force(tariff, date(2026, 1, 1))  # the end date is excluded
    assert new is not None and new.revision == 2
    assert revision_in_force(tariff, date(2024, 12, 31)) is None
    with pytest.raises(LookupError, match="no tariff"):
        find_tariff(index, "IE", "example-energy", "other")


def source() -> tuple[Any, StaticSource]:
    files = two_revisions()
    text = json.dumps(build_index(files, TODAY))
    return parse_index(text), StaticSource(text, files)


def test_load_revision_checks_the_file() -> None:
    index, src = source()
    assert parse_index(src.read_index()) == index
    entry = find_tariff(index, "IE", "example-energy", "example-nightboost").revisions[2]
    assert load_revision(src, entry).revision == 2


def test_a_changed_file_fails_its_checksum() -> None:
    index, src = source()
    entry = find_tariff(index, "IE", "example-energy", "example-nightboost").revisions[2]
    changed = json.dumps(doc(2, "2026-01-01", None, name="Edited"))
    with pytest.raises(ChecksumMismatch, match=PATH2):
        load_revision(StaticSource(src.index_text, {**src.files, PATH2: changed}), entry)


def test_a_local_entry_without_a_checksum_is_not_checked() -> None:
    index, src = source()
    entry = find_tariff(index, "IE", "example-energy", "example-nightboost").revisions[2]
    unchecked = type(entry)(entry.revision, entry.effective_from, entry.effective_to, entry.path, None)
    edited = json.dumps(doc(2, "2026-01-01", None, name="Edited"))
    assert load_revision(StaticSource("", {PATH2: edited}), unchecked).name == "Edited"


def test_a_file_that_disagrees_with_its_entry_is_refused() -> None:
    index, src = source()
    entry = find_tariff(index, "IE", "example-energy", "example-nightboost").revisions[2]
    unchecked = type(entry)(entry.revision, entry.effective_from, entry.effective_to, entry.path, None)
    other = json.dumps(doc(2, "2026-02-01", None))
    with pytest.raises(DefinitionError, match="does not agree"):
        load_revision(StaticSource("", {PATH2: other}), unchecked)
    with pytest.raises(DefinitionError, match="not in the source"):
        load_revision(StaticSource("", {}), unchecked)


def index_doc() -> dict[str, Any]:
    return json.loads(json.dumps(build_index(two_revisions(), TODAY)))


def tariff_of(d: dict[str, Any]) -> dict[str, Any]:
    return d["countries"]["IE"]["providers"]["example-energy"]["tariffs"]["example-nightboost"]


Edit = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    ("edit", "text"),
    [
        (lambda d: d.update(schema=2), "schema"),
        (lambda d: d.update(extra=1), "extra"),
        (lambda d: d.update(generated="yesterday"), "generated"),
        (lambda d: d["countries"].update({"Ireland": {}}), "country code"),
        (lambda d: d["countries"]["IE"].update(extra=1), "extra"),
        (lambda d: d["countries"]["IE"]["providers"].update({"Bad Id": {}}), "lowercase"),
        (lambda d: tariff_of(d).update(latest=9), "not one of the revisions"),
        (lambda d: tariff_of(d).update(completeness="maybe"), "one of"),
        (lambda d: tariff_of(d).update(revisions={}), "at least one"),
        (lambda d: tariff_of(d)["revisions"].update({"two": {}}), "revision number"),
        (lambda d: tariff_of(d)["revisions"]["1"].update(effective_to="2025-01-01"), "after"),
        (lambda d: tariff_of(d)["revisions"]["1"].update(checksum="md5:00"), "sha256"),
        (lambda d: tariff_of(d)["revisions"]["1"].update(extra=1), "extra"),
    ],
)
def test_parse_index_refusals(edit: Edit, text: str) -> None:
    d = index_doc()
    edit(d)
    with pytest.raises(DefinitionError, match=text):
        parse_index(json.dumps(d))
