"""The arithmetic the payload promises (US-4.1 AC2).

api.md states it as a sentence: *"`contribution` values sum to `overall_score`.
The score is reproducible by hand from this payload."* That is the whole claim
of the explainable score — if it is off by 0.1, a user who checks the column
concludes the system is making numbers up, and they would be right to.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import pytest

from app.services.matching.dimensions import DimensionScore
from app.services.matching.service import assemble, overall
from app.services.matching.weights import (
    NEUTRAL,
    RANKING_VERSION,
    WEIGHTS,
    Dimension,
    DimensionStatus,
)


def scores(**by_name: Decimal) -> dict[Dimension, DimensionScore]:
    """Six results, defaulting to neutral, with the named ones overridden."""
    return {
        dimension: DimensionScore(
            score=by_name.get(dimension.value, NEUTRAL),
            status=DimensionStatus.SCORED,
            reason="",
        )
        for dimension in Dimension
    }


def test_the_weights_sum_to_one():
    """If they do not, `overall_score` is not out of 100 and every number in the
    breakdown is quietly on a different scale from the one documented."""
    assert sum(WEIGHTS.values()) == Decimal("1")


def test_the_breakdown_is_always_the_six_in_weight_order():
    """Never sorted by score.

    A fixed order is what makes two payloads diffable and what lets a user check
    the arithmetic by reading straight down one column. Sorting would also
    silently change which row the eye lands on first, which is a presentational
    claim the data does not make.
    """
    rows = assemble(scores(semantic=Decimal("0.1"), salary=Decimal("0.99")))
    assert [row.dimension for row in rows] == list(Dimension)
    assert [row.dimension for row in rows] == list(WEIGHTS)


def test_contributions_sum_to_the_overall_score_across_the_whole_space():
    """The property, swept rather than spot-checked.

    5^6 = 15,625 combinations of dimension scores, including every rounding
    edge that a x.x5 value produces. An example-based test passes on the happy
    path and misses the one combination where a half-cent goes the wrong way —
    which is precisely how a payload ends up failing its own stated guarantee.
    """
    values = [Decimal("0"), Decimal("0.3333"), Decimal("0.5"), Decimal("0.6667"), Decimal("1")]

    for combination in itertools.product(values, repeat=len(Dimension)):
        assigned = dict(zip(Dimension, combination, strict=True))
        rows = assemble(
            {
                dimension: DimensionScore(
                    score=value, status=DimensionStatus.SCORED, reason=""
                )
                for dimension, value in assigned.items()
            }
        )
        total = overall(rows)
        assert sum(row.contribution for row in rows) == total, assigned


def test_a_perfect_match_scores_exactly_one_hundred():
    rows = assemble(
        {
            dimension: DimensionScore(
                score=Decimal("1"), status=DimensionStatus.SCORED, reason=""
            )
            for dimension in Dimension
        }
    )
    assert overall(rows) == Decimal("100.0")


def test_four_neutral_dimensions_compress_the_range_to_twenty_eighty():
    """The honest cost of the fixed-weight decision, asserted rather than
    described.

    When only semantic and skill can be computed — the case the data audit found
    — the other four sit at 0.5 and the score is confined to [20, 80] with a
    constant +20 offset. Pinning it here means that if someone later "fixes" the
    range by renormalising the weights, this test says so out loud rather than
    letting the change pass as a cosmetic improvement.

    **This is the bound for that case, not for every score.** Measured over 420
    real pairs the observed range is 21.8 to 91.0: profiles that have filled in
    their preferences, plus the education fallback that reads
    `education_records`, do let all six dimensions run. `scored_weight` has a
    median of 0.60 across those pairs, which is what the 60% figure refers to.
    """
    unknowns = {"experience", "education", "location", "salary"}

    worst = assemble(scores(semantic=Decimal("0"), skill=Decimal("0")))
    best = assemble(scores(semantic=Decimal("1"), skill=Decimal("1")))

    assert overall(worst) == Decimal("20.0")
    assert overall(best) == Decimal("80.0")
    # The two that carry real signal are exactly the 60% that moves the number.
    assert sum(WEIGHTS[d] for d in Dimension if d.value not in unknowns) == Decimal("0.60")


def test_the_ranking_version_is_recorded():
    """ADR-005's migration path depends on it: a learned ranker writes under a
    different version alongside these, and the comparison is then a query."""
    assert RANKING_VERSION == "v1-hand-tuned"


@pytest.mark.parametrize(
    ("status", "counts"),
    [
        (DimensionStatus.SCORED, True),
        (DimensionStatus.NOT_STATED, False),
        (DimensionStatus.NEEDS_PROFILE, False),
        (DimensionStatus.NEEDS_DATA, False),
    ],
)
def test_only_scored_rows_count_as_evidence(status: DimensionStatus, counts: bool):
    """The deliberate asymmetry.

    A NOT_STATED education row awards a full 10 points — the absence of a
    requirement is not a penalty — but contributes nothing to `scored_weight`.
    Those points are real and they are not evidence about this person, and
    conflating the two would let the interface claim a confidence it has not
    earned.
    """
    from app.services.matching.service import _scored_weight

    rows = assemble(
        {
            dimension: DimensionScore(
                score=Decimal("1"),
                status=status if dimension is Dimension.EDUCATION else DimensionStatus.SCORED,
                reason="",
            )
            for dimension in Dimension
        }
    )
    expected = Decimal("1") if counts else Decimal("1") - WEIGHTS[Dimension.EDUCATION]
    assert _scored_weight(rows) == expected
