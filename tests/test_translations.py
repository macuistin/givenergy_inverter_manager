"""strings.json and translations/en.json must describe the same forms."""

from __future__ import annotations

import json

from tests.helpers import PKG

_COMPONENT = PKG


def _shape(node):
    if isinstance(node, dict):
        return {key: _shape(value) for key, value in node.items()}
    return None


def test_en_json_has_the_same_structure_as_strings_json():
    strings = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((_COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert _shape(en) == _shape(strings)


def test_en_json_text_matches_strings_json():
    strings = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((_COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert en == strings


def test_en_json_is_a_byte_copy_of_strings_json():
    assert (_COMPONENT / "translations" / "en.json").read_bytes() == (_COMPONENT / "strings.json").read_bytes()
