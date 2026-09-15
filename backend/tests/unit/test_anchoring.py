"""Anchoring a suggestion to the text it claims to rewrite.

Both halves matter and they pull against each other. Too strict and nothing is
ever appliable, which is what the first real run hit. Too loose and a rewrite
lands on a sentence the user never chose to change, which is worse than doing
nothing at all.
"""

from __future__ import annotations

import pytest

from app.services.resume.anchoring import find_span, replace_span

# A line as pdfplumber actually returns it: wrapped, with the indent of the
# original layout still in the middle of the sentence.
WRAPPED = "hosting. The application is efficiently\n        deployed on Vercel.\n"


class TestWhitespaceIsFlexible:
    def test_a_line_wrapped_by_extraction_still_matches(self) -> None:
        """The failure that made every suggestion unappliable on the first real
        run. The model writes the sentence back on one line; the resume has a
        newline and eight spaces in the middle of it."""
        assert find_span(WRAPPED, "The application is efficiently deployed on Vercel.") is not None

    @pytest.mark.parametrize(
        "original",
        [
            "Reduced  p99   latency",
            "Reduced\np99 latency",
            "Reduced\tp99 latency",
        ],
        ids=["extra-spaces", "newline", "tab"],
    )
    def test_any_run_of_whitespace_is_one_separator(self, original: str) -> None:
        assert find_span("Reduced p99 latency by 35%.", original) is not None

    def test_the_replacement_keeps_the_rest_of_the_document(self) -> None:
        result = replace_span(
            WRAPPED, "The application is efficiently deployed on Vercel.", "Deployed on Vercel."
        )

        assert result is not None
        assert result.startswith("hosting. ")
        assert "Deployed on Vercel." in result
        assert "efficiently" not in result


class TestWordsAreNot:
    """The line between "formatting differs" and "this is different text"."""

    def test_a_paraphrase_does_not_match(self) -> None:
        """The actual cause of the first real failure: the model merged two
        bullets into a sentence that appears nowhere in the resume, then called
        it the original."""
        invented = (
            "Deployed the application seamlessly on Vercel, ensuring high performance "
            "and reliability capable of handling concurrent traffic."
        )

        assert find_span(WRAPPED, invented) is None

    @pytest.mark.parametrize(
        "original",
        [
            "The application is deployed on Vercel.",
            "The application is efficiently deployed on Netlify.",
            "The app is efficiently deployed on Vercel.",
        ],
        ids=["word-dropped", "word-changed", "word-substituted"],
    )
    def test_a_missing_or_changed_word_does_not_match(self, original: str) -> None:
        assert find_span(WRAPPED, original) is None

    def test_words_must_be_in_order(self) -> None:
        assert find_span(WRAPPED, "Vercel on deployed") is None

    def test_punctuation_is_matched_literally(self) -> None:
        """Escaped, so a resume containing regex characters cannot turn a lookup
        into a pattern that matches something else."""
        text = "Built a C++ (v17) parser [fast] and shipped it."

        assert find_span(text, "C++ (v17) parser [fast]") is not None
        assert find_span(text, "C.. .v17. parser .fast.") is None


class TestEdges:
    def test_only_the_first_occurrence_is_replaced(self) -> None:
        """A bullet repeated twice is two separate claims. Replacing both would
        change one the user did not review."""
        text = "Led the team. Led the team."

        result = replace_span(text, "Led the team.", "Directed the team.")

        assert result == "Directed the team. Led the team."

    def test_nothing_to_find_returns_none_rather_than_the_text(self) -> None:
        """None rather than the unchanged text, so a caller cannot mistake "no
        change was needed" for "the text was not found"."""
        assert replace_span("some resume text", "absent line", "new") is None

    @pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
    def test_an_empty_original_anchors_to_nothing(self, empty: str) -> None:
        """A zero-width match would otherwise succeed at offset 0 and insert the
        rewrite at the top of the document."""
        assert find_span("some resume text", empty) is None
        assert replace_span("some resume text", empty, "new") is None
