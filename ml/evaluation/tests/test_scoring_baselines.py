"""The baselines the interview scorer has to beat.

The length baseline is the one that matters, so most of this file is about
making sure it is genuinely strong. A baseline that is easy to beat proves
nothing when it is beaten.
"""

from __future__ import annotations

import pytest

from evaluation.metrics import mean_absolute_error, pearson, spearman
from evaluation.scoring_baselines import constant_baseline, length_baseline


class TestConstant:
    def test_it_predicts_the_mean(self):
        assert constant_baseline([0.2, 0.4, 0.6]) == pytest.approx([0.4, 0.4, 0.4])

    def test_its_correlation_is_undefined_rather_than_zero(self):
        human = [0.2, 0.4, 0.6]

        assert pearson(constant_baseline(human), human) is None

    def test_it_sets_a_real_floor_for_error(self):
        # Not zero: the mean is wrong about every answer that is not average,
        # and that gap is what the model has to improve on.
        human = [0.0, 0.5, 1.0]

        assert mean_absolute_error(constant_baseline(human), human) == pytest.approx(1 / 3)

    def test_empty_input_gives_empty_output(self):
        assert constant_baseline([]) == []


class TestLength:
    def test_the_longest_answer_gets_the_highest_mark_awarded(self):
        texts = ["short", "a much longer answer than the others here", "medium one"]
        human = [0.1, 0.5, 0.9]

        predicted = length_baseline(texts, human)

        assert predicted[1] == 0.9
        assert predicted[0] == 0.1

    def test_it_borrows_the_human_distribution_rather_than_inventing_a_scale(self):
        """What makes it a serious baseline instead of a straw man.

        Raw character counts are not marks. Comparing them directly would
        understate the baseline on MAE for a reason that has nothing to do with
        whether length predicts quality.
        """
        texts = ["a", "bb", "ccc"]
        human = [0.4, 0.5, 0.6]

        assert sorted(length_baseline(texts, human)) == sorted(human)

    def test_when_length_tracks_quality_it_scores_perfectly(self):
        """The case the model has to beat.

        If good answers are simply longer ones, a word counter is already a
        good scorer, and anything more elaborate has to earn its place.
        """
        texts = ["a" * n for n in (10, 50, 100, 200)]
        human = [0.2, 0.4, 0.7, 0.9]

        predicted = length_baseline(texts, human)

        assert spearman(predicted, human) == pytest.approx(1.0)
        assert mean_absolute_error(predicted, human) == pytest.approx(0.0)

    def test_when_length_is_unrelated_to_quality_it_does_badly(self):
        # And so the comparison in the report means something in both
        # directions.
        texts = ["a" * n for n in (10, 50, 100, 200)]
        human = [0.9, 0.2, 0.7, 0.4]

        assert spearman(length_baseline(texts, human), human) < 0.5

    def test_ties_in_length_share_the_marks_they_span(self):
        """Otherwise the result depends on the order answers arrived in, and
        two runs over the same data would disagree."""
        texts = ["aaaa", "bbbb", "cc"]
        human = [0.2, 0.6, 1.0]

        predicted = length_baseline(texts, human)

        # The two four-character answers span the 0.6 and 1.0 marks.
        assert predicted[0] == predicted[1] == pytest.approx(0.8)
        assert predicted[2] == 0.2

    def test_order_of_input_does_not_change_the_result(self):
        texts = ["aaaa", "bbbb", "cc"]
        human = [0.2, 0.6, 1.0]

        forward = length_baseline(texts, human)
        reversed_ = length_baseline(texts[::-1], human[::-1])

        assert forward == reversed_[::-1]

    def test_mismatched_lengths_are_a_programming_error(self):
        with pytest.raises(ValueError):
            length_baseline(["a", "b"], [0.5])

    def test_empty_input_gives_empty_output(self):
        assert length_baseline([], []) == []
