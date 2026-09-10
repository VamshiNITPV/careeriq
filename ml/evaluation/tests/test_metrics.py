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
    dcg,
    ndcg_at_k,
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
