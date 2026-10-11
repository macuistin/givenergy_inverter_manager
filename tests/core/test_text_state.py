"""fit_state fits a sentence into Home Assistant's 255 character state limit."""

from __future__ import annotations

import random

import pytest

from custom_components.givenergy_inverter_manager.const import STATE_MAX_LENGTH
from custom_components.givenergy_inverter_manager.core.text_state import (
    ELLIPSIS,
    FittedText,
    fit_state,
)

# The decision text of the 2026-10-11 log line: 271 characters, as the charge plan builds it.
LONG_REASON = (
    "Forward simulation: 7.3kWh forecast (forecast integration, x0.87 recent accuracy "
    "(cautious forecast, 50% of the way from the typical to the low estimate)). Target 100%. "
    "Not skipping: Battery may run low. Estimated shortfall: 1.0kWh before solar starts. "
    "Per-slot load profile used. (capped at configured max 90%)"
)


def _state(text: str, limit: int = STATE_MAX_LENGTH) -> str:
    return fit_state(text, limit).state


def _words_are_whole(text: str, shortened: str) -> bool:
    """True when every word of shortened is a whole word of text, bar trailing punctuation."""
    body = shortened.removesuffix(ELLIPSIS).split()
    source = text.split()
    if body[: len(body) - 1] != source[: len(body) - 1]:
        return False
    return source[len(body) - 1].rstrip(".,;:") == body[-1].rstrip(".,;:")


def test_the_limit_is_255():
    assert STATE_MAX_LENGTH == 255


class TestFittedText:
    def test_a_text_that_fits_is_its_own_state_and_was_not_cut(self):
        fitted = fit_state("Skipping overnight charge.")

        assert fitted == FittedText("Skipping overnight charge.", "Skipping overnight charge.")
        assert fitted.was_cut is False

    def test_a_long_text_keeps_the_whole_text_beside_the_state(self):
        fitted = fit_state(LONG_REASON)

        assert fitted.full == LONG_REASON
        assert fitted.state != LONG_REASON
        assert fitted.was_cut is True


class TestTheLogLine:
    def test_the_reason_is_longer_than_a_state_can_be(self):
        assert len(LONG_REASON) > STATE_MAX_LENGTH

    def test_it_is_cut_to_fit(self):
        assert len(_state(LONG_REASON)) <= STATE_MAX_LENGTH

    def test_it_is_cut_at_the_end_of_a_sentence(self):
        shortened = _state(LONG_REASON)

        assert shortened.endswith("1.0kWh before solar starts" + ELLIPSIS)
        assert "Per-slot" not in shortened

    def test_the_start_of_the_text_is_kept(self):
        assert LONG_REASON.startswith(_state(LONG_REASON).removesuffix(ELLIPSIS))


class TestTextThatFits:
    def test_a_short_text_is_returned_as_it_is(self):
        assert _state("Skipping overnight charge.") == "Skipping overnight charge."

    def test_an_empty_text_is_returned_as_it_is(self):
        assert _state("") == ""

    def test_a_text_of_exactly_255_characters_is_not_cut(self):
        text = ("word " * 60)[:255]
        assert len(text) == 255

        assert _state(text) is text

    def test_a_text_of_256_characters_is_cut_to_fit(self):
        text = ("word " * 60)[:256]
        assert len(text) == 256

        shortened = _state(text)

        assert len(shortened) <= STATE_MAX_LENGTH
        assert shortened.endswith(ELLIPSIS)


class TestWhereTheCutFalls:
    def test_a_text_with_no_sentence_boundary_is_cut_between_words(self):
        text = " ".join(f"word{n}" for n in range(200))

        shortened = _state(text)

        assert len(shortened) <= STATE_MAX_LENGTH
        assert shortened.endswith(ELLIPSIS)
        assert _words_are_whole(text, shortened)

    def test_a_word_is_never_split(self):
        text = "alpha " * 40 + "supercalifragilistic" + " omega" * 40

        for limit in range(30, 200):
            shortened = _state(text, limit)
            assert len(shortened) <= limit
            assert _words_are_whole(text, shortened), limit

    def test_the_end_of_a_sentence_is_preferred_to_the_end_of_a_clause(self):
        text = "First part, second part. " + "tail words, " * 30

        assert _state(text, 40) == "First part, second part" + ELLIPSIS

    def test_the_end_of_a_clause_is_used_when_there_is_no_sentence_end_to_use(self):
        text = "one two three, " + "four five six seven eight " * 20

        assert _state(text, 25) == "one two three" + ELLIPSIS

    def test_a_sentence_end_too_early_to_be_worth_keeping_is_passed_over(self):
        text = "Hi. " + "and then some more words follow " * 20

        shortened = _state(text, 100)

        assert len(shortened) > 50
        assert shortened != "Hi" + ELLIPSIS

    def test_a_dash_separator_starts_a_clause_that_is_dropped(self):
        text = "Battery at 40% during Night — " + "topping up to the floor " * 20

        assert _state(text, 40) == "Battery at 40% during Night" + ELLIPSIS

    def test_the_ellipsis_does_not_follow_a_full_stop(self):
        shortened = _state("A short sentence. " * 30, 50)

        assert shortened.endswith("sentence" + ELLIPSIS)
        assert ".…" not in shortened

    def test_one_word_longer_than_the_limit_is_cut_where_it_must_be(self):
        shortened = _state("x" * 400)

        assert shortened == "x" * (STATE_MAX_LENGTH - 1) + ELLIPSIS


class TestCharactersNotBytes:
    def test_a_text_of_255_multibyte_characters_is_not_cut(self):
        text = "é" * 255
        assert len(text.encode()) > STATE_MAX_LENGTH

        assert _state(text) == text

    def test_a_text_of_256_multibyte_characters_is_cut_to_255_characters(self):
        shortened = _state("é" * 256)

        assert len(shortened) == STATE_MAX_LENGTH
        assert shortened.endswith(ELLIPSIS)

    def test_degree_signs_arrows_and_dashes_count_as_one_each(self):
        text = ("Water at 48.2°C → heating — " * 20).strip()

        shortened = _state(text)

        assert len(text) > STATE_MAX_LENGTH
        assert len(shortened) <= STATE_MAX_LENGTH
        assert _words_are_whole(text, shortened.replace(" —" + ELLIPSIS, ELLIPSIS))


class TestAnyText:
    @pytest.mark.parametrize("seed", range(40))
    def test_the_result_always_fits_and_starts_the_text(self, seed):
        rng = random.Random(seed)
        pieces = ["alpha", "beta,", "gamma.", "δελτα", "°C", "—", "(note)", "x" * 30, "7.3kWh;"]
        text = " ".join(rng.choice(pieces) for _ in range(rng.randint(1, 300)))

        shortened = _state(text)

        assert len(shortened) <= STATE_MAX_LENGTH
        if len(text) <= STATE_MAX_LENGTH:
            assert shortened == text
        else:
            assert shortened.endswith(ELLIPSIS)
            assert text.startswith(shortened.removesuffix(ELLIPSIS).rstrip(" ,;:.—·-("))
