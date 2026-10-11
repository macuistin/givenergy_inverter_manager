"""
alt_heat_label.py: the user's word for the alternative water heating, as it reads in a sentence.

The label is typed by the user ("Oil", "Gas", "Heat pump") and goes into the advice sentences, so
it is cleaned here: whitespace squeezed, cut to ALT_HEAT_LABEL_MAX_LENGTH characters, and the
default put back when nothing is left. A sentence needs two forms of it: one that starts the
sentence ("Gas is cheaper than electricity") and one inside it ("Heat the water with the gas
system"). The inside form is lower case unless the label is all capitals, so LPG stays LPG.

The dashboard template for the schedule line applies the same rule in Jinja
(dashboard/templates.py), so a sentence reads the same wherever it is shown.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const import ALT_HEAT_LABEL_MAX_LENGTH, DEFAULT_ALT_HEAT_LABEL


@dataclass(frozen=True)
class LabelForms:
    """A label for the start of a sentence and for the middle of one."""

    start: str
    inside: str


def clean_label(label: object) -> str:
    """The label as stored: single spaces, at most the maximum length, never empty."""
    text = " ".join(str(label).split()) if isinstance(label, str) else ""
    return text[:ALT_HEAT_LABEL_MAX_LENGTH].rstrip() or DEFAULT_ALT_HEAT_LABEL


def label_forms(label: object) -> LabelForms:
    """The two forms of *label* a sentence needs, after cleaning it."""
    clean = clean_label(label)
    inside = clean if clean.isupper() else clean.lower()
    return LabelForms(start=clean[0].upper() + clean[1:], inside=inside)
