"""The dataset's own claims, checked (ml.md section 7.3).

`cases.py` makes several structural promises in prose -- a hundred answers, ten
profiles ten times each, no profile twice on one question. Prose does not stay
true. These assert it.

The tests that matter most are the last two classes: the digest is what stops a
stale label being averaged into a real number, and it fails silently if it is
wrong.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from datasets.interview_scoring import (
    ANSWERS,
    ANSWERS_BY_ID,
    DIMENSIONS,
    PROFILES,
    QUESTIONS,
    QUESTIONS_BY_ID,
    ScoresStale,
    content_digest,
    load_human_scores,
)

EXPECTED_ANSWERS = 100
EXPECTED_QUESTIONS = 20


def _write_scores(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    path = tmp_path / "human_scores.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _full_marks(answer_id: str) -> dict[str, dict[str, float]]:
    return {answer_id: dict.fromkeys(DIMENSIONS, 0.8)}


class TestShape:
    def test_there_are_a_hundred_answers_to_twenty_questions(self):
        assert len(ANSWERS) == EXPECTED_ANSWERS
        assert len(QUESTIONS) == EXPECTED_QUESTIONS

    def test_ids_are_unique(self):
        # A duplicate id would silently drop an answer from ANSWERS_BY_ID and
        # from the marks, and the count would still read 100.
        assert len(ANSWERS_BY_ID) == len(ANSWERS)
        assert len(QUESTIONS_BY_ID) == len(QUESTIONS)

    def test_every_answer_belongs_to_a_real_question(self):
        for answer in ANSWERS:
            assert answer.question_id in QUESTIONS_BY_ID, answer.id

    def test_every_question_has_five_answers(self):
        for question in QUESTIONS:
            attached = [a for a in ANSWERS if a.question_id == question.id]
            assert len(attached) == 5, question.id

    def test_every_question_carries_a_rubric(self):
        # `completeness` is marked against expected_points. A question without
        # one makes that dimension unmarkable, and the score would still come
        # back looking complete.
        for question in QUESTIONS:
            assert len(question.expected_points) >= 4, question.id


class TestTheSpread:
    """The design claim: the five dimensions are made to pull apart."""

    def test_every_profile_appears_exactly_ten_times(self):
        counts = dict.fromkeys(PROFILES, 0)
        for answer in ANSWERS:
            counts[answer.profile] += 1

        assert set(counts) == set(PROFILES)
        assert all(count == 10 for count in counts.values()), counts

    def test_no_question_carries_the_same_profile_twice(self):
        """Otherwise a question's five answers could be five of the same thing,
        and the within-question comparison would say nothing."""
        for question in QUESTIONS:
            profiles = [a.profile for a in ANSWERS if a.question_id == question.id]
            assert len(set(profiles)) == 5, question.id

    def test_the_profiles_that_pull_dimensions_apart_are_present(self):
        """The set's whole reason for existing, asserted rather than assumed.

        Without these three a model that emits one number five times would
        correlate perfectly on every dimension and the evaluation would call
        that success.
        """
        present = {a.profile for a in ANSWERS}
        assert "correct_but_rambling" in present  # technical high, structure low
        assert "polished_but_wrong" in present  # structure high, technical low
        assert "adjacent" in present  # technical high, relevance low

    def test_the_rambling_answers_are_actually_unstructured(self):
        """They are supposed to be hard to read, not merely long.

        An answer written in tidy sentences would be marked well on structure by
        any honest human, and then the row tests nothing.
        """
        rambling = [a for a in ANSWERS if a.profile == "correct_but_rambling"]
        for answer in rambling:
            sentences = answer.text.count(". ")
            assert sentences <= 2, f"{answer.id} reads as ordinary prose"

    def test_the_injection_answers_actually_try_to_instruct_the_marker(self):
        wanted = ("1.0", "score", "award", "rubric", "instruction")
        for answer in (a for a in ANSWERS if a.profile == "injection"):
            lowered = answer.text.lower()
            assert any(word in lowered for word in wanted), answer.id


class TestTheDigest:
    def test_it_is_stable_across_calls(self):
        # A digest that moved on its own would make every scores file stale on
        # the next run and teach everybody to skip the check.
        assert content_digest() == content_digest()

    def test_it_is_a_named_hash_rather_than_a_bare_hex_string(self):
        # So a file recording one can be read years later without guessing.
        assert content_digest().startswith("sha256:")


class TestLoadingMarks:
    def test_a_file_from_a_different_dataset_is_refused(self, tmp_path):
        """The whole point of the digest.

        Nothing crashes when a mark meant for one answer lands on another. The
        metrics just come back worse, and the obvious reading of that is that
        the model regressed.
        """
        path = _write_scores(
            tmp_path,
            {"digest": "sha256:something-else", "scores": _full_marks("a001")},
        )
        with pytest.raises(ScoresStale, match="changed"):
            load_human_scores(path)

    def test_a_file_recording_no_digest_at_all_is_refused(self, tmp_path):
        # Hand-written or from an older format. Absence is not agreement.
        path = _write_scores(tmp_path, {"scores": _full_marks("a001")})
        with pytest.raises(ScoresStale):
            load_human_scores(path)

    def test_marks_matching_the_digest_load(self, tmp_path):
        path = _write_scores(
            tmp_path,
            {
                "digest": content_digest(),
                "scored_by": "a human",
                "scores": _full_marks("a001"),
            },
        )
        loaded = load_human_scores(path)

        assert loaded.count == 1
        assert loaded.scored_by == "a human"
        assert loaded.overall("a001") == pytest.approx(0.8)

    def test_the_overall_is_the_mean_of_the_five(self, tmp_path):
        """Computed, not asked for -- the same rule the scorer follows.

        Comparing a human's holistic impression against the model's computed
        mean would measure the difference between those two things as though it
        were disagreement about the answer.
        """
        marks = {"a001": dict(zip(DIMENSIONS, [1.0, 0.5, 0.5, 0.5, 0.5], strict=True))}
        path = _write_scores(tmp_path, {"digest": content_digest(), "scores": marks})

        assert load_human_scores(path).overall("a001") == pytest.approx(0.6)

    def test_partial_scoring_is_allowed(self, tmp_path):
        # Marking a hundred answers is more than one sitting.
        path = _write_scores(
            tmp_path, {"digest": content_digest(), "scores": _full_marks("a050")}
        )
        assert load_human_scores(path).count == 1

    def test_a_row_missing_a_dimension_is_refused(self, tmp_path):
        """Unlike a missing row, a missing dimension is a mistake, not progress.

        Averaging over the four that survived would read as a complete mark.
        """
        marks = _full_marks("a001")
        del marks["a001"]["structure"]
        path = _write_scores(tmp_path, {"digest": content_digest(), "scores": marks})

        with pytest.raises(ValueError, match="structure"):
            load_human_scores(path)

    @pytest.mark.parametrize("bad", [1.5, -0.1, "0.8", None, True])
    def test_a_mark_outside_the_scale_is_refused(self, tmp_path, bad):
        marks = _full_marks("a001")
        marks["a001"]["technical"] = bad
        path = _write_scores(tmp_path, {"digest": content_digest(), "scores": marks})

        with pytest.raises(ValueError, match="technical"):
            load_human_scores(path)

    def test_a_mark_for_an_answer_that_does_not_exist_is_refused(self, tmp_path):
        # Usually a typo in an id, and silently ignoring it would quietly
        # shrink the scored set while the count still looked plausible.
        path = _write_scores(
            tmp_path, {"digest": content_digest(), "scores": _full_marks("a999")}
        )
        with pytest.raises(ValueError, match="a999"):
            load_human_scores(path)
