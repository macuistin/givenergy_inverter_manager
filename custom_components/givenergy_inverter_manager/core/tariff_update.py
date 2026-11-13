"""
tariff_update.py - decide what a newer revision of a followed store tariff means for the options.

A tariff chosen from the store is copied into the saved options with a `tariff_source` record
(`wizard_store.source_record`). The updater reads the same tariff from the store again and asks
`decide` what to do. A revision applies whole, on the day it starts: the standing charge, levy, VAT
and discount cannot change part way through a billing period, because the accumulators reverse them
from the stored import cost with one value per period.

Pure Python. It reads no clock and no network: the caller passes the definition and the day.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..lib.tariff import TariffDefinition
from .wizard_store import SOURCE_KIND, choose_tariff, pays_for_export

PREVIOUS_KEY = "previous"
NOT_LISTED = "the store no longer lists this tariff"


class Outcome(StrEnum):
    CURRENT = "current"  # nothing newer, or not a followed tariff
    APPLY = "apply"  # a newer revision is in force and the user follows updates
    OFFER = "offer"  # a newer revision is in force and the user turned updates off
    ATTENTION = "attention"  # the tariff ended, or the new revision does not fit the options


@dataclass(frozen=True)
class UpdateDecision:
    """What to do. `options` and `record` are set for an apply, `reasons` for attention."""

    outcome: Outcome
    options: dict[str, Any] = field(default_factory=dict)
    record: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


CURRENT = UpdateDecision(Outcome.CURRENT)


def follows_store(record: Mapping[str, Any] | None) -> bool:
    """True while the saved tariff is a store tariff nobody has edited by hand."""
    return bool(record) and record is not None and record.get("kind") == SOURCE_KIND


def ended(record: Mapping[str, Any] | None) -> UpdateDecision:
    """The decision when the store no longer lists the followed tariff."""
    if not follows_store(record):
        return CURRENT
    return UpdateDecision(Outcome.ATTENTION, reasons=[NOT_LISTED])


def decide(
    record: Mapping[str, Any] | None,
    definition: TariffDefinition,
    options: Mapping[str, Any],
    bill_start_day: int,
) -> UpdateDecision:
    """Compare the revision now in force with the one copied into *options*."""
    if record is None or not follows_store(record):
        return CURRENT
    if definition.effective_from.isoformat() <= str(record.get("effective_from", "")):
        return CURRENT
    choice = choose_tariff(definition, bill_start_day, record.get("export_rate"))
    if not choice.usable:
        return UpdateDecision(Outcome.ATTENTION, reasons=choice.reasons)
    new_record = _next_record(record, definition, options, choice.options)
    if not record.get("auto_update", True):
        return UpdateDecision(Outcome.OFFER, record=new_record)
    return UpdateDecision(Outcome.APPLY, options=choice.options, record=new_record)


def _next_record(
    record: Mapping[str, Any],
    definition: TariffDefinition,
    options: Mapping[str, Any],
    new_options: Mapping[str, Any],
) -> dict[str, Any]:
    """The record for the new revision, holding what Undo needs to put the old one back."""
    previous = {key: options[key] for key in new_options if key in options}
    old = {k: v for k, v in record.items() if k != PREVIOUS_KEY}
    kept = {k: v for k, v in old.items() if k != "export_rate" or not pays_for_export(definition)}
    return {
        **kept,
        "name": definition.name,
        "provider_name": definition.provider.name,
        "effective_from": definition.effective_from.isoformat(),
        PREVIOUS_KEY: {"options": previous, "record": old},
    }


def undo(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """The options (record included) that put back the revision before the last update."""
    previous = record.get(PREVIOUS_KEY)
    if not previous:
        return None
    old = dict(previous["record"])
    old["auto_update"] = False  # undoing means the user does not want this revision
    return {**previous["options"], "tariff_source": old}
