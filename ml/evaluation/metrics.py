"""Ranking metrics (ml.md section 4.3).

Pure functions over `(rank-ordered labels)`. No numpy, no scipy, no database —
an evaluation harness whose metrics cannot be unit-tested in isolation is a
harness nobody can trust, and a wrong NDCG silently invalidates every number
reported from it.

## The two conventions that have to be stated, not assumed

**Graded labels, binary precision.** Labels are `HIGH=3 / MEDIUM=2 / LOW=1 /
IRRELEVANT=0` (ml.md section 4.3). Precision@K and MRR need a yes/no notion of
relevant, and this module draws the line at **>= 2**: a MEDIUM job is one a
person would genuinely consider, a LOW one is "adjacent but not really". Drawing
it at >= 1 instead would score "adjacent" as a hit and inflate every precision
figure — the threshold is the single most consequential choice in this file,
which is why it is a named constant rather than a literal in three places.

**Exponential gain.** NDCG uses `gain = 2**label - 1`, the standard formulation,
so HIGH(3)=7 is meaningfully more than MEDIUM(2)=3 rather than merely 1.5x. With
linear gain a ranker that puts two MEDIUMs above one HIGH scores better than one
that does the opposite, which is not what "graded relevance" is supposed to mean.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Labels at or above this count as relevant for the binary metrics.
RELEVANT_AT = 2

#: The label scale, for callers that need to validate input.
MAX_LABEL = 3


def precision_at_k(labels_in_rank_order: Sequence[int], k: int) -> float | None:
    """Fraction of the top K that are relevant.

    Returns `None` rather than 0.0 when fewer than K results exist. A query that
    could only return three jobs has not achieved "precision@5 = 0.4" — it has
    no precision@5 at all, and averaging a fabricated 0.4 into a corpus-wide
    figure understates a ranker for a reason that has nothing to do with ranking.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if len(labels_in_rank_order) < k:
        return None
    top = labels_in_rank_order[:k]
    return sum(1 for label in top if label >= RELEVANT_AT) / k


def dcg(labels_in_rank_order: Sequence[int], k: int) -> float:
    """Discounted cumulative gain over the first K, with exponential gain."""
    return sum(
        (2**label - 1) / math.log2(position + 2)
        for position, label in enumerate(labels_in_rank_order[:k])
    )


def ndcg_at_k(
    labels_in_rank_order: Sequence[int], k: int, *, ideal: Sequence[int] | None = None
) -> float | None:
    """DCG@K over the best achievable DCG@K.

    `ideal` defaults to this query's own labels sorted best-first, which measures
    "did you order what you retrieved as well as it could be ordered". Pass the
    full labelled set for the query instead to measure against the best possible
    ordering of *everything that exists* — a ranker that never retrieved the one
    HIGH job should not score 1.0 for ordering the MEDIUMs it did retrieve
    perfectly.

    Returns `None` when no labelled item carries any gain: 0/0 is undefined, and
    reporting 0.0 would say the ranker failed at a query that had nothing to find.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    best = sorted(ideal if ideal is not None else labels_in_rank_order, reverse=True)
    ideal_dcg = dcg(best, k)
    if ideal_dcg == 0:
        return None
    return dcg(labels_in_rank_order, k) / ideal_dcg


def reciprocal_rank(labels_in_rank_order: Sequence[int]) -> float:
    """1 / rank of the first relevant result, or 0.0 if there is none.

    0.0 is correct here, unlike in the functions above: "no relevant result
    anywhere in the list" is a real and meaningful outcome, not missing data.
    """
    for position, label in enumerate(labels_in_rank_order):
        if label >= RELEVANT_AT:
            return 1 / (position + 1)
    return 0.0


def recall_at_k(
    retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int
) -> float | None:
    """Fraction of the known-relevant items that the first K retrieved contain.

    Tracked separately from the ranking metrics, and ml.md is explicit about why:
    a failure here is invisible in precision and NDCG. If stage one never
    retrieves the ideal job, perfect ranking cannot recover it, and the symptom
    reads as bad ranking — which is a long way to debug.

    Returns `None` when nothing is known to be relevant, for the same reason
    `ndcg_at_k` does: the denominator is zero, not the answer.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    wanted = set(relevant_ids)
    if not wanted:
        return None
    found = wanted.intersection(retrieved_ids[:k])
    return len(found) / len(wanted)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation between two sequences, with ties averaged.

    **Not in ml.md's table, and added deliberately.** The metrics above are
    per-query, and this project has **two distinct people** in its corpus — so
    averaging Precision@5 over two queries is an anecdote, however carefully
    computed. Correlation runs over *pairs*, of which there are a hundred, and it
    answers the question those metrics cannot at this sample size: does the score
    move with relevance at all?

    Returns `None` when either side is constant, where the coefficient is
    undefined rather than zero.
    """
    if len(xs) != len(ys):
        raise ValueError("sequences must be the same length")
    if len(xs) < 2:
        return None

    rx, ry = _tied_ranks(xs), _tied_ranks(ys)
    n = len(rx)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    dx = [value - mean_x for value in rx]
    dy = [value - mean_y for value in ry]
    numerator = sum(a * b for a, b in zip(dx, dy, strict=True))
    denominator = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    if denominator == 0:
        return None
    return numerator / denominator


def _tied_ranks(values: Sequence[float]) -> list[float]:
    """Ranks, with tied values sharing the average of the ranks they span.

    Tie handling is load-bearing rather than fussy: scores are rounded to one
    decimal place and labels take four values, so ties are the common case here,
    not an edge case. Assigning them arbitrary distinct ranks would make the
    coefficient depend on input order.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return ranks
