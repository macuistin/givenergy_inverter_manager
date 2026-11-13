"""What a newer revision of a followed store tariff does to the saved options."""

from __future__ import annotations

from datetime import date, time

from custom_components.givenergy_inverter_manager.core.tariff_update import (
    NOT_LISTED,
    Outcome,
    decide,
    ended,
    undo,
)
from custom_components.givenergy_inverter_manager.core.wizard_store import (
    choose_tariff,
    source_options,
    source_record,
)
from custom_components.givenergy_inverter_manager.lib.tariff import (
    Locale,
    TariffConfig,
    definition_from_config,
)
from custom_components.givenergy_inverter_manager.lib.tariff.periods import RatePeriod

PICKED = {"country": "IE", "provider": "acme", "tariff": "home", "area": "all"}


def _definition(effective: date, **changes: object):  # noqa: ANN202
    values = {
        "rate_periods": [RatePeriod("Night", 0.18, time(23), time(8))],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 0.0,
        "bill_start_day": 1,
    }
    values.update(changes)
    return definition_from_config(
        TariffConfig(**values),  # type: ignore[arg-type]
        Locale("EUR", "IE", "Europe/Dublin", effective),
    )


def _saved(auto_update: bool = True):  # noqa: ANN202
    first = _definition(date(2026, 1, 1))
    record = {**source_record(PICKED, first), "auto_update": auto_update}
    return record, source_options(record, choose_tariff(first, 1))


def test_the_same_or_an_older_revision_changes_nothing() -> None:
    record, options = _saved()
    assert decide(record, _definition(date(2026, 1, 1)), options, 1).outcome is Outcome.CURRENT


def test_a_hand_edited_tariff_is_never_touched() -> None:
    record, options = _saved()
    edited = {**record, "kind": "based_on"}
    assert decide(edited, _definition(date(2026, 6, 1)), options, 1).outcome is Outcome.CURRENT
    assert decide(None, _definition(date(2026, 6, 1)), options, 1).outcome is Outcome.CURRENT


def test_a_newer_revision_applies_whole_and_keeps_the_old_one_for_undo() -> None:
    record, options = _saved()
    newer = _definition(date(2026, 6, 1), base_rate=0.4, standing_charge=0.9)
    decision = decide(record, newer, options, 1)
    assert decision.outcome is Outcome.APPLY
    assert decision.options["base_rate"] == 0.4
    assert decision.options["standing_charge_per_day"] == 0.9
    assert decision.record["effective_from"] == "2026-06-01"
    restored = undo(decision.record)
    assert restored is not None
    assert restored["base_rate"] == 0.365
    assert restored["tariff_source"]["effective_from"] == "2026-01-01"
    assert restored["tariff_source"]["auto_update"] is False
    assert "previous" not in restored["tariff_source"]


def test_with_updates_off_a_newer_revision_is_only_offered() -> None:
    record, options = _saved(auto_update=False)
    decision = decide(record, _definition(date(2026, 6, 1), base_rate=0.4), options, 1)
    assert decision.outcome is Outcome.OFFER
    assert decision.options == {}


def test_a_revision_the_options_cannot_hold_needs_attention() -> None:
    record, options = _saved()
    odd = _definition(date(2026, 6, 1), rate_periods=[RatePeriod("Night", 0.18, time(23, 10), time(8))])
    decision = decide(record, odd, options, 1)
    assert decision.outcome is Outcome.ATTENTION
    assert decision.reasons


def test_an_ended_tariff_needs_attention_but_a_hand_edited_one_does_not() -> None:
    record, _ = _saved()
    assert ended(record).reasons == [NOT_LISTED]
    assert ended({**record, "kind": "based_on"}).outcome is Outcome.CURRENT


def test_undo_with_nothing_to_undo_is_none() -> None:
    record, _ = _saved()
    assert undo(record) is None
