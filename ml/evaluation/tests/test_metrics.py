"""Metrics, checked against values computed by hand.

The point of this file is that every number 6.4 reports depends on these
functions, and a wrong NDCG does not fail loudly — it produces a plausible
figure. So the important cases are computed longhand in the assertions rather
than captured from a first run, which would only pin whatever the code did.
"""

from __future__ import annotations

import math

import pytest

from evaluation.metrics import (
    RELEVANT_AT,
    confusion_at,
    dcg,
    mean_absolute_error,
    ndcg_at_k,
    pearson,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    spearman,
)


class TestPrecision:
    def test_counts_medium_and_high_as_relevant(self):
        # The threshold choice made visible: LOW(1) is not a hit.
        assert precision_at_k([3, 2, 1, 0, 0], 5) == pytest.approx(0.4)

    def test_the_threshold_is_the_documented_one(self):
        """Guards the single most consequential constant in the module.

        Moving it to >= 1 would score "adjacent but not really" as a hit and
        inflate every precision figure in the report.
        """
        assert RELEVANT_AT == 2

    def test_a_perfect_and_an_empty_top_five(self):
        assert precision_at_k([3, 3, 2, 2, 2], 5) == 1.0
        assert precision_at_k([1, 0, 1, 0, 1], 5) == 0.0

    def test_too_few_results_is_none_not_zero(self):
        """A query that could only return three jobs has no precision@5.

        Averaging a fabricated 0.4 into the corpus figure would penalise the
        ranker for the size of the corpus.
        """
        assert precision_at_k([3, 3, 3], 5) is None

    def test_rejects_a_nonsense_k(self):
        with pytest.raises(ValueError):
            precision_at_k([3, 2], 0)


class TestNdcg:
    def test_dcg_against_a_longhand_value(self):
        # gain = 2^l - 1, discount = log2(position + 2).
        # [3, 0, 2] -> 7/log2(2) + 0/log2(3) + 3/log2(4) = 7 + 0 + 1.5
        assert dcg([3, 0, 2], 3) == pytest.approx(7 + 0 + 3 / 2)

    def test_uses_exponential_gain_so_one_high_beats_two_mediums(self):
        """The reason for 2^l - 1 rather than linear gain.

        Under linear gain [2, 2, 0] scores the same as [3, 0, 0] at the top and
        the grading stops meaning anything. A HIGH is worth more than two
        MEDIUMs, and the formulation has to say so.
        """
        assert dcg([3, 0, 0], 3) > dcg([2, 2, 0], 3)

    def test_a_perfect_ordering_scores_one(self):
        assert ndcg_at_k([3, 3, 2, 1, 0], 5) == pytest.approx(1.0)

    def test_a_reversed_ordering_scores_well_below_one(self):
        assert ndcg_at_k([0, 1, 2, 3, 3], 5) < 0.6

    def test_an_ideal_from_the_full_labelled_set_punishes_a_missed_high(self):
        """Ordering what you retrieved perfectly is not the same as retrieving
        the right things.

        Without passing `ideal`, a ranker that never surfaced the one HIGH job
        scores 1.0 for neatly ordering the MEDIUMs it did find.
        """
        retrieved = [2, 2]
        assert ndcg_at_k(retrieved, 2) == pytest.approx(1.0)
        assert ndcg_at_k(retrieved, 2, ideal=[3, 2, 2]) < 0.75

    def test_nothing_relevant_anywhere_is_none_not_zero(self):
        # 0/0 is undefined; 0.0 would claim the ranker failed a query that had
        # nothing to find.
        assert ndcg_at_k([0, 0, 0], 3) is None


class TestReciprocalRank:
    @pytest.mark.parametrize(
        ("labels", "expected"),
        [
            ([3, 0, 0], 1.0),
            ([0, 2, 0], 0.5),
            ([1, 1, 3], pytest.approx(1 / 3)),
        ],
    )
    def test_finds_the_first_relevant_position(self, labels, expected):
        assert reciprocal_rank(labels) == expected

    def test_zero_is_the_right_answer_when_nothing_is_relevant(self):
        """Unlike the other functions, 0.0 is meaningful here: "no relevant
        result anywhere" is an outcome, not missing data."""
        assert reciprocal_rank([1, 0, 1]) == 0.0


class TestRecall:
    def test_counts_how_many_known_relevant_items_were_retrieved(self):
        assert recall_at_k(["a", "b", "c"], ["a", "c", "z"], 3) == pytest.approx(2 / 3)

    def test_only_looks_at_the_first_k(self):
        """The whole point of Recall@200: a relevant job at position 201 was not
        retrieved, however well the rest was ordered."""
        assert recall_at_k(["x", "a"], ["a"], 1) == 0.0

    def test_no_known_relevant_items_is_none(self):
        assert recall_at_k(["a"], [], 5) is None


class TestPearsonAndMAE:
    """The interview-scoring pair (ml.md section 7.3).

    Reported together because each is blind to something the other sees, and the
    tests below are mostly about that blindness rather than about the arithmetic.
    """

    def test_a_perfect_linear_relationship_is_one(self):
        assert pearson([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]) == pytest.approx(1.0)

    def test_a_constant_offset_still_correlates_perfectly(self):
        """The reason MAE is reported beside it, in one assertion.

        A scorer marking every answer 0.3 low has the shape of the judgement
        right and is still wrong about every single answer. Pearson says 1.0.
        """
        human = [0.2, 0.5, 0.8]
        model = [value - 0.3 for value in human]

        assert pearson(model, human) == pytest.approx(1.0)
        assert mean_absolute_error(model, human) == pytest.approx(0.3)

    def test_mae_is_blind_to_the_ordering_pearson_measures(self):
        """And the converse, so neither is trusted alone.

        Two answers marked with each other's scores: every individual error is
        small, and the model has inverted which answer was better.
        """
        human = [0.4, 0.6]
        model = [0.6, 0.4]

        assert mean_absolute_error(model, human) == pytest.approx(0.2)
        assert pearson(model, human) == pytest.approx(-1.0)

    def test_it_measures_distance_not_rank(self):
        """Pearson rather than Spearman here, because both sides are marks in
        [0, 1] meaning the same thing -- so how far apart they are is real
        information rather than an artefact of two unrelated scales."""
        assert spearman([1, 2, 3], [1, 2, 1000]) == pytest.approx(1.0)
        assert pearson([1, 2, 3], [1, 2, 1000]) == pytest.approx(0.866, abs=1e-3)

    def test_a_known_value_longhand(self):
        # xs = [0, 1, 2], ys = [0, 1, 1]. Means 1 and 2/3.
        # dx = [-1, 0, 1], dy = [-2/3, 1/3, 1/3]; numerator = 2/3 + 0 + 1/3 = 1.
        # denominator = sqrt(2 * (4/9 + 1/9 + 1/9)) = sqrt(4/3).
        assert pearson([0, 1, 2], [0, 1, 1]) == pytest.approx(1 / math.sqrt(4 / 3))

    def test_a_constant_side_is_none_rather_than_zero(self):
        # A model that gives every answer 0.7 has no correlation to report, and
        # 0.0 would read as "measured, and found unrelated".
        assert pearson([0.7, 0.7, 0.7], [0.1, 0.5, 0.9]) is None

    def test_too_few_points_is_none(self):
        assert pearson([0.5], [0.5]) is None

    def test_mae_of_nothing_is_none_rather_than_zero(self):
        # 0.0 would read as perfect agreement over an empty dataset.
        assert mean_absolute_error([], []) is None

    @pytest.mark.parametrize("metric", [pearson, mean_absolute_error])
    def test_mismatched_lengths_are_a_programming_error(self, metric):
        with pytest.raises(ValueError):
            metric([0.1, 0.2], [0.1])


class TestSpearman:
    def test_a_perfect_monotonic_relationship_is_one(self):
        assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)

    def test_a_perfect_inversion_is_minus_one(self):
        assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_it_measures_rank_not_distance(self):
        """Spearman, not Pearson, because the scores and the labels are on
        completely different scales and only their ordering is comparable."""
        assert spearman([1, 2, 3], [1, 2, 1000]) == pytest.approx(1.0)

    def test_ties_share_the_average_rank(self):
        """Ties are the common case here, not an edge case — scores round to one
        decimal place and labels take four values. Handled badly, the
        coefficient would depend on the order the pairs happened to arrive in.
        """
        forward = spearman([1, 1, 2, 2], [5, 5, 9, 9])
        shuffled = spearman([2, 1, 2, 1], [9, 5, 9, 5])
        assert forward == pytest.approx(1.0)
        assert shuffled == pytest.approx(1.0)

    def test_a_constant_side_is_none_rather_than_zero(self):
        # The coefficient is undefined, and 0.0 would read as "no relationship"
        # — a claim about the data rather than about the arithmetic.
        assert spearman([1, 1, 1], [1, 2, 3]) is None

    def test_too_few_points_is_none(self):
        assert spearman([1], [2]) is None

    def test_mismatched_lengths_are_a_programming_error(self):
        with pytest.raises(ValueError):
            spearman([1, 2], [1])

    def test_a_known_value_longhand(self):
        """Two discordant pairs out of four, computed by hand.

        xs ranks [1,2,3,4]; ys = [1,2,4,3] -> ranks [1,2,4,3].
        sum d^2 = 0 + 0 + 1 + 1 = 2, n = 4
        rho = 1 - 6*2 / (4 * 15) = 1 - 12/60 = 0.8
        """
        assert spearman([1, 2, 3, 4], [1, 2, 4, 3]) == pytest.approx(0.8)

    def test_agrees_with_the_textbook_formula_on_untied_data(self):
        xs = [1, 2, 3, 4, 5, 6]
        ys = [2, 1, 4, 3, 6, 5]
        n = len(xs)
        # 1 - 6*sum(d^2) / (n(n^2-1)), valid only without ties.
        expected = 1 - 6 * sum((a - b) ** 2 for a, b in zip(xs, ys, strict=True)) / (
            n * (n * n - 1)
        )
        assert spearman(xs, ys) == pytest.approx(expected)
        assert not math.isnan(expected)


class TestConfusion:
    def test_counts_the_four_outcomes(self):
        scores = [0.99, 0.96, 0.90, 0.50]
        labels = [1, 0, 1, 0]
        c = confusion_at(scores, labels, 0.95)
        assert (c.true_positives, c.false_positives, c.false_negatives, c.true_negatives) == (
            1,
            1,
            1,
            1,
        )
        assert c.precision == pytest.approx(0.5)
        assert c.recall == pytest.approx(0.5)
        assert c.f1 == pytest.approx(0.5)

    def test_the_boundary_is_inclusive(self):
        """A threshold quoted as 0.95 must include a pair scoring exactly 0.95.

        Invisible until a score lands on the boundary, and then it silently
        changes the answer — which is why it is pinned.
        """
        assert confusion_at([0.95], [1], 0.95).true_positives == 1
        assert confusion_at([0.95], [1], 0.9500001).false_negatives == 1

    def test_flagging_nothing_gives_no_precision_rather_than_zero(self):
        """0/0. Reporting 0.0 would say the detector was wrong about everything
        it claimed, when it claimed nothing at all."""
        c = confusion_at([0.1, 0.2], [1, 0], 0.95)
        assert c.precision is None
        assert c.recall == 0.0

    def test_nothing_to_find_gives_no_recall_rather_than_zero(self):
        # A statement about the dataset, not about the detector.
        c = confusion_at([0.99], [0], 0.95)
        assert c.recall is None
        assert c.precision == 0.0

    def test_f1_is_none_when_either_side_is_undefined(self):
        assert confusion_at([0.1], [0], 0.95).f1 is None

    def test_a_perfect_detector(self):
        c = confusion_at([0.99, 0.10], [1, 0], 0.95)
        assert c.precision == 1.0
        assert c.recall == 1.0
        assert c.f1 == 1.0

    def test_mismatched_lengths_are_a_programming_error(self):
        with pytest.raises(ValueError):
            confusion_at([0.9], [1, 0], 0.5)
