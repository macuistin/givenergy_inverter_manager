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


SETUP_STEPS = {
    "system",
    "inverter_entities",
    "tariff",
    "tariff_rates",
    "forecast",
    "hot_water",
    "confirm",
    "reconfigure",
    "reconfigure_manual",
}
OPTIONS_STEPS = {
    "init",
    "tariff",
    "tariff_rates",
    "bill",
    "schedule_change",
    "battery",
    "forecast",
    "hot_water",
    "ev",
    "confirm",
}


def _strings() -> dict:
    return json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))


def test_the_strings_have_exactly_the_steps_the_wizards_show():
    strings = _strings()

    assert set(strings["config"]["step"]) == SETUP_STEPS
    assert set(strings["options"]["step"]) == OPTIONS_STEPS


def test_every_step_has_a_title_and_a_description():
    strings = _strings()

    for kind in ("config", "options"):
        for step_id, step in strings[kind]["step"].items():
            assert step.get("title"), f"{kind}.{step_id} has no title"
            assert step.get("description"), f"{kind}.{step_id} has no description"


def test_every_error_a_wizard_page_can_return_has_text():
    from custom_components.givenergy_inverter_manager.core.wizard_model import ERROR_KEYS

    strings = _strings()
    options = set(strings["options"]["error"])
    config = set(strings["config"]["error"])

    setup_errors = {"missing_entities", "rate_period_zero_length", "rate_period_duplicate_name",
                    "rate_period_name_missing", "base_rate_required", "base_rate_name_missing",
                    "too_many_periods"}
    assert set(ERROR_KEYS) <= options | config
    assert setup_errors <= config
    assert set(ERROR_KEYS) - {"missing_entities"} <= options


def test_the_abort_reasons_the_flows_use_have_text():
    abort = _strings()["config"]["abort"]

    assert {"already_configured", "already_in_progress", "reconfigure_successful", "wrong_inverter"} <= set(abort)


def test_no_wizard_text_uses_an_em_dash():
    text = json.dumps({k: _strings()[k] for k in ("config", "options")}, ensure_ascii=False)

    assert "—" not in text
