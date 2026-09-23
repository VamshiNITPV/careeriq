"""The agreement report's arithmetic (ml.md section 7.3).

`compute_report` is pure, so the report can be checked against scorers whose
behaviour is known in advance -- a perfect one, one that is offset, one that is
secretly a word counter. That last is the case the whole evaluation exists to
catch, and it is the only way to find out whether the report would actually
catch it.

Nothing here writes to the dataset directory. A synthetic `human_scores.json`
put where the real one belongs only has to be forgotten once.
"""

from __future__ import annotations

import pytest
from datasets.interview_scoring import ANSWERS_BY_ID, DIMENSIONS, HumanScores

from evaluation.run_scoring_eval import (
    TARGET_MAE,
    TARGET_PEARSON,
    TARGET_SPEARMAN,
    compute_report,
)

#: Twenty answers spanning several profiles, so the per-profile table has rows.
USABLE = sorted(ANSWERS_BY_ID)[:20]


def _human(marks_by_answer: dict[str, float]) -> HumanScores:
    """A human who gave the same mark on all five dimensions of each answer."""
    return HumanScores(
        digest="sha256:test",
        scored_by="test",
        marks={
            answer_id: dict.fromkeys(DIMENSIONS, value)
            for answer_id, value in marks_by_answer.items()
        },
    )


def _spread() -> dict[str, float]:
    """Human marks spread across the scale, uncorrelated with answer length."""
    return {
        answer_id: round(0.05 + (index * 7 % 19) / 20, 3)
        for index, answer_id in enumerate(USABLE)
    }


def _model_from(marks: dict[str, float]) -> dict[str, dict[str, float]]:
    return {a: dict.fromkeys(DIMENSIONS, v) for a, v in marks.items()}


class TestAPerfectScorer:
    @pytest.fixture
    def report(self):
        marks = _spread()
        return compute_report(
            usable=USABLE, human=_human(marks), model_scores=_model_from(marks)
        )

    def test_it_meets_every_target(self, report):
        assert report["below_target"] == []
        assert report["overall"]["pearson"] == pytest.approx(1.0)
        assert report["overall"]["spearman"] == pytest.approx(1.0)
        assert report["overall"]["mae"] == pytest.approx(0.0)

    def test_the_per_profile_gap_is_zero(self, report):
        for profile, row in report["per_profile"].items():
            assert row["gap"] == pytest.approx(0.0), profile


class TestAScorerThatIsConsistentlyGenerous:
    """The case Pearson alone would pass.

    A scorer marking every answer 0.3 high has the shape of the judgement
    exactly right and is wrong about every single answer.
    """

    @pytest.fixture
    def report(self):
        marks = _spread()
        generous = {a: min(1.0, v + 0.3) for a, v in marks.items()}
        return compute_report(
            usable=USABLE, human=_human(marks), model_scores=_model_from(generous)
        )

    def test_the_correlations_look_excellent(self, report):
        assert report["overall"]["pearson"] > 0.9
        assert report["overall"]["spearman"] > 0.9

    def test_but_the_error_fails_the_target(self, report):
        assert report["overall"]["mae"] > TARGET_MAE
        assert report["below_target"] == ["mae"]

    def test_and_every_profile_shows_a_positive_gap(self, report):
        # Signed rather than absolute, so overmarking and undermarking are
        # distinguishable -- they are different failures with different fixes.
        for profile, row in report["per_profile"].items():
            assert row["gap"] > 0, profile


class TestAScorerThatHasInvertedTheOrdering:
    """The case MAE alone would pass.

    Small individual errors, and it has decided the weak answer was the strong
    one -- which is the only thing the product actually needs it to get right.
    """

    def test_the_rank_targets_catch_it(self):
        marks = _spread()
        ordered = sorted(marks.values())
        inverted = dict(zip(marks, reversed(ordered), strict=True))

        report = compute_report(
            usable=USABLE, human=_human(marks), model_scores=_model_from(inverted)
        )

        assert report["overall"]["pearson"] < 0
        assert "pearson" in report["below_target"]
        assert "spearman" in report["below_target"]


class TestAScorerThatIsSecretlyAWordCounter:
    """The reason the length baseline is in the report at all.

    A scorer that had learned nothing except "longer is better" can still
    correlate respectably with a human, because good interview answers do tend
    to be longer. The report has to make that visible rather than reporting a
    number that looks like understanding.
    """

    def test_the_length_baseline_matches_it_rather_than_trailing_it(self):
        # The human marks here are genuinely length-driven, so the model and the
        # baseline are doing the same thing. If the report did not print the
        # baseline, the model's figure alone would read as success.
        by_length = sorted(USABLE, key=lambda a: len(ANSWERS_BY_ID[a].text))
        marks = {a: round(i / (len(by_length) - 1), 3) for i, a in enumerate(by_length)}

        report = compute_report(
            usable=USABLE, human=_human(marks), model_scores=_model_from(marks)
        )

        assert report["overall"]["spearman"] == pytest.approx(1.0)
        # And the baseline gets there too, with no model call.
        assert report["baselines"]["length"]["spearman"] == pytest.approx(1.0)

    def test_the_baseline_does_not_track_marks_that_ignore_length(self):
        # Otherwise the comparison above would be true of every dataset and
        # would say nothing about this one.
        marks = _spread()
        report = compute_report(
            usable=USABLE, human=_human(marks), model_scores=_model_from(marks)
        )

        length = report["baselines"]["length"]["spearman"]
        assert length is not None and abs(length) < 0.9


class TestAScorerThatEmitsOneNumberFiveTimes:
    """The failure the five-dimension design is exposed to.

    A model ignoring the rubric and repeating one impression would look fine on
    the headline, because the headline is the mean. The per-dimension table is
    where it shows.
    """

    def test_the_per_dimension_rows_diverge_when_the_human_marked_separately(self):
        # A human who marked technical and structure differently, against a
        # model that gave the same number to both.
        human = HumanScores(
            digest="sha256:test",
            scored_by="test",
            marks={
                answer_id: {
                    "technical": round(0.05 + (index * 7 % 19) / 20, 3),
                    "relevance": 0.5,
                    "completeness": 0.5,
                    "communication": 0.5,
                    # Deliberately the opposite of technical.
                    "structure": round(1.0 - (0.05 + (index * 7 % 19) / 20), 3),
                }
                for index, answer_id in enumerate(USABLE)
            },
        )
        flat = {
            a: dict.fromkeys(DIMENSIONS, human.marks[a]["technical"]) for a in USABLE
        }

        report = compute_report(usable=USABLE, human=human, model_scores=flat)

        assert report["per_dimension"]["technical"]["pearson"] == pytest.approx(1.0)
        assert report["per_dimension"]["structure"]["pearson"] == pytest.approx(-1.0)


class TestTheTargets:
    def test_they_are_the_ones_ml_md_states(self):
        # Load-bearing constants, so a change to them is a visible change here
        # rather than a quiet one in a source file.
        assert TARGET_PEARSON == 0.70
        assert TARGET_SPEARMAN == 0.75
        assert TARGET_MAE == 0.15

    def test_a_constant_scorer_fails_on_an_undefined_correlation(self):
        """`None` must count as missing the target, not as passing it.

        A model giving every answer 0.5 has a correlation that cannot be
        computed, and treating "not computable" as "not below the threshold"
        would let the most degenerate possible scorer through.
        """
        marks = _spread()
        flat = {a: dict.fromkeys(DIMENSIONS, 0.5) for a in USABLE}

        report = compute_report(
            usable=USABLE, human=_human(marks), model_scores=flat
        )

        assert report["overall"]["pearson"] is None
        assert "pearson" in report["below_target"]
        assert "spearman" in report["below_target"]
