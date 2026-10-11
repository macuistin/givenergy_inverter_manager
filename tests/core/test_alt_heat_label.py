"""The label of the alternative water heating: cleaned for storage, shaped for a sentence."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    ALT_HEAT_LABEL_MAX_LENGTH,
    DEFAULT_ALT_HEAT_LABEL,
)
from custom_components.givenergy_inverter_manager.core.alt_heat_label import (
    clean_label,
    label_forms,
)


class TestCleanLabel:
    @pytest.mark.parametrize(
        ("typed", "stored"),
        [
            ("Oil", "Oil"),
            ("Heat pump", "Heat pump"),
            ("  Gas  ", "Gas"),
            ("Heat   pump", "Heat pump"),
            ("Wood\npellets", "Wood pellets"),
        ],
    )
    def test_whitespace_is_squeezed(self, typed, stored):
        assert clean_label(typed) == stored

    @pytest.mark.parametrize("typed", ["", "   ", "\n\t", None, 0, 4.5, [], {}])
    def test_nothing_typed_gives_the_default(self, typed):
        assert clean_label(typed) == DEFAULT_ALT_HEAT_LABEL

    def test_a_long_label_is_cut_to_the_maximum(self):
        assert clean_label("x" * 500) == "x" * ALT_HEAT_LABEL_MAX_LENGTH

    def test_a_cut_never_leaves_a_trailing_space(self):
        typed = "a" * (ALT_HEAT_LABEL_MAX_LENGTH - 1) + " b"
        assert clean_label(typed) == "a" * (ALT_HEAT_LABEL_MAX_LENGTH - 1)

    def test_a_label_of_exactly_the_maximum_is_kept(self):
        typed = "y" * ALT_HEAT_LABEL_MAX_LENGTH
        assert clean_label(typed) == typed

    def test_the_maximum_is_the_twenty_characters_of_the_form(self):
        assert ALT_HEAT_LABEL_MAX_LENGTH == 20


class TestLabelForms:
    @pytest.mark.parametrize(
        ("typed", "start", "inside"),
        [
            ("Oil", "Oil", "oil"),
            ("oil", "Oil", "oil"),
            ("Gas", "Gas", "gas"),
            ("Heat pump", "Heat pump", "heat pump"),
            ("Heat Pump", "Heat Pump", "heat pump"),
            ("LPG", "LPG", "LPG"),
            ("Wood", "Wood", "wood"),
        ],
    )
    def test_start_and_inside_forms(self, typed, start, inside):
        forms = label_forms(typed)
        assert (forms.start, forms.inside) == (start, inside)

    def test_an_empty_label_gives_the_default_forms(self):
        assert label_forms("").start == "Oil"
        assert label_forms("").inside == "oil"

    def test_a_long_label_gives_cut_forms(self):
        forms = label_forms("z" * 100)
        assert len(forms.start) == ALT_HEAT_LABEL_MAX_LENGTH
        assert len(forms.inside) == ALT_HEAT_LABEL_MAX_LENGTH
