"""Reading a scoring reply strictly (US-8.3).

`parse_score` is pure, so every rule is testable against literal strings. These
numbers are shown to somebody as a judgement of their answer and fed to the
policy that picks the next question, so a reply that is nearly right must be
refused rather than rounded into shape.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.services.interview.scoring import DIMENSIONS, ScoreRejected, parse_score

ANSWER = "I used dual writes during the cutover, then verified row counts matched."


def reply(**overrides: object) -> str:
    payload: dict[str, object] = {
        "scores": dict.fromkeys(DIMENSIONS, 0.6),
        "feedback": "Solid, but no mention of rollback.",
        "strengths": ["names a concrete technique"],
        "improvements": ["say what you would do if parity failed"],
        "cited_spans": [
            {"start": 0, "end": 18, "text": "I used dual writes", "note": "the technique"}
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def parse(raw: str, *, answer: str = ANSWER):
    return parse_score(raw, answer=answer)


class TestTheFiveDimensions:
    def test_a_well_formed_reply_is_read(self) -> None:
        score = parse(reply())

        assert set(score.dimensions) == set(DIMENSIONS)
        assert score.feedback

    def test_every_dimension_is_required(self) -> None:
        """Four of five is a different measurement wearing the same name.

        Averaging over whatever survived would produce a number that reads as a
        complete mark, and US-8.3 AC1 asks for five.
        """
        for missing in DIMENSIONS:
            scores = {name: 0.6 for name in DIMENSIONS if name != missing}
            with pytest.raises(ScoreRejected, match=missing):
                parse(reply(scores=scores))

    @pytest.mark.parametrize("bad", [1.5, -0.1, 4, "0.6", None, True])
    def test_a_score_outside_the_scale_is_refused_not_clamped(self, bad: object) -> None:
        """A model returning 4.5 has misread the scale, not scored highly.

        Clamping would turn a parsing failure into a perfect mark, which is the
        worst available reading of it.
        """
        scores = dict.fromkeys(DIMENSIONS, 0.6)
        scores["technical"] = bad
        with pytest.raises(ScoreRejected, match="technical"):
            parse(reply(scores=scores))

    def test_the_bounds_themselves_are_allowed(self) -> None:
        for edge in (0.0, 1.0):
            score = parse(reply(scores=dict.fromkeys(DIMENSIONS, edge)))
            assert score.overall == Decimal(str(edge))


class TestTheOverall:
    def test_it_is_computed_rather_than_taken_from_the_model(self) -> None:
        """Two authoritative values can disagree, and invisibly.

        A model returning 0.9 beside five dimensions averaging 0.4 is not
        reporting a weighting, it is reporting nothing.
        """
        scores = dict.fromkeys(DIMENSIONS, 0.4)
        score = parse(reply(scores=scores, overall=0.9))

        assert score.overall == Decimal("0.4")

    def test_it_is_the_mean_of_the_five(self) -> None:
        scores = {
            "technical": 1.0,
            "relevance": 0.5,
            "completeness": 0.5,
            "communication": 0.5,
            "structure": 0.5,
        }
        # Equal weights, because ml.md names the five without ranking them.
        # Inventing a ranking would be a claim about what matters in an
        # interview that nothing here has measured.
        assert parse(reply(scores=scores)).overall == Decimal("0.6")


class TestCitations:
    """US-8.3 AC2, made checkable by ml.md's rule that offsets must be valid."""

    def test_a_valid_span_carries_the_answers_own_words(self) -> None:
        score = parse(reply())

        assert len(score.cited_spans) == 1
        span = score.cited_spans[0]
        # Taken from the answer at those offsets, not from what the model said
        # it quoted -- so the citation cannot drift from what was written.
        assert span.text == ANSWER[span.start : span.end]

    @pytest.mark.parametrize(
        "span",
        [
            {"start": -1, "end": 10},
            {"start": 5, "end": 5},
            {"start": 10, "end": 5},
            {"start": 0, "end": 9_999},
            {"start": "0", "end": "10"},
            {"start": True, "end": 10},
            "not an object",
        ],
    )
    def test_a_span_outside_the_answer_is_dropped(self, span: object) -> None:
        score = parse(reply(cited_spans=[span]))

        assert score.cited_spans == ()

    def test_a_quote_that_disagrees_with_its_offsets_is_dropped(self) -> None:
        """A citation pointing elsewhere than it says is worse than none.

        It will be believed. The offsets are the truth and the quote is the
        model's account of them, so a mismatch means the account is wrong.
        """
        score = parse(
            reply(cited_spans=[{"start": 0, "end": 10, "text": "something else entirely"}])
        )

        assert score.cited_spans == ()

    def test_whitespace_differences_in_the_quote_are_forgiven(self) -> None:
        # The model reflows text; that is not a disagreement about which words
        # it is pointing at.
        score = parse(
            reply(cited_spans=[{"start": 0, "end": 18, "text": "I used   dual\n writes"}])
        )

        assert len(score.cited_spans) == 1

    def test_one_bad_span_does_not_discard_the_good_ones(self) -> None:
        """The marks are still usable when a citation is malformed.

        Losing four good ones because the fifth had a bad offset is a worse
        answer, not a safer one -- the same reasoning `prompts/parsing.py`
        gives for keeping partial results.
        """
        score = parse(
            reply(
                cited_spans=[
                    {"start": 0, "end": 6},
                    {"start": 9_000, "end": 9_100},
                    {"start": 7, "end": 11},
                ]
            )
        )

        assert len(score.cited_spans) == 2


class TestRefusals:
    @pytest.mark.parametrize("raw", ["not json", "[]", "null", ""])
    def test_a_reply_that_is_not_the_object_is_refused(self, raw: str) -> None:
        with pytest.raises(ScoreRejected):
            parse(raw)

    def test_missing_feedback_is_refused(self) -> None:
        # The number without the explanation is the half that helps least.
        with pytest.raises(ScoreRejected, match="feedback"):
            parse(reply(feedback=""))

    def test_missing_scores_is_refused(self) -> None:
        with pytest.raises(ScoreRejected, match="scores"):
            parse(reply(scores="excellent"))
