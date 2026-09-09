"""Cursor paging over a ranking (api.md section 2.5).

This is the codebase's first cursor pagination — `GET /jobs` uses offset — and
the failure it exists to prevent is subtle: with an unstable sort, a row can be
served on two consecutive pages or on neither, and nothing errors. So the tests
here are mostly about the *order*, not about the slicing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.services.matching.dimensions import SkillBuckets
from app.services.matching.recommend import _sort_key, decode_cursor, encode_cursor
from app.services.matching.service import MatchResult
from app.services.matching.weights import RANKING_VERSION


def result(score: str, job_id: uuid.UUID | None = None) -> MatchResult:
    return MatchResult(
        user_id=uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        resume_version_id=uuid.uuid4(),
        overall_score=Decimal(score),
        breakdown=(),
        scored_weight=Decimal("0.6"),
        skills=SkillBuckets(matched=(), partial=(), missing=()),
        ranking_version=RANKING_VERSION,
        computed_at=datetime.now(UTC),
        semantic_available=True,
    )


class TestSortKey:
    def test_orders_by_score_descending(self):
        low, high = result("40.0"), result("80.0")
        assert sorted([low, high], key=_sort_key) == [high, low]

    def test_breaks_ties_on_job_id_so_the_order_is_total(self):
        """The tie-break is the whole basis of the cursor being correct.

        Scores are quantised to one decimal place over a 200-row set, so ties
        are ordinary rather than rare. Two rows that compare equal have no
        defined order, which means one of them can appear on both page one and
        page two — or on neither — with nothing anywhere going red.
        """
        ids = sorted(uuid.uuid4() for _ in range(5))
        tied = [result("55.5", job_id) for job_id in reversed(ids)]

        ordered = sorted(tied, key=_sort_key)

        assert [r.job_id for r in ordered] == ids

    def test_the_key_is_stable_across_repeated_sorts(self):
        rows = [result("55.5") for _ in range(20)] + [result("70.0") for _ in range(20)]
        shuffled = rows[::-1]
        first = [r.job_id for r in sorted(rows, key=_sort_key)]
        second = [r.job_id for r in sorted(shuffled, key=_sort_key)]
        assert first == second


class TestCursor:
    def test_round_trips_to_the_row_it_names(self):
        row = result("68.4")
        assert decode_cursor(encode_cursor(row)) == _sort_key(row)

    def test_is_opaque_rather_than_a_readable_offset(self):
        """A client that can read a cursor starts depending on the sort key, and
        the sort key is then frozen by clients we cannot see."""
        row = result("68.4")
        token = encode_cursor(row)
        assert str(row.job_id) not in token
        assert "68.4" not in token

    def test_garbage_returns_none_rather_than_raising(self):
        """A cursor travels in a URL, so it is user input: truncated by a mail
        client, mangled by a share sheet, or simply invented. None of those is
        worth a 500, and the caller treats None as "start from the beginning" —
        the same answer a first request gets."""
        for junk in ["", "!!!!", "Zm9v", "not-base64-at-all", "%%%", "aGVsbG86d29ybGQ="]:
            assert decode_cursor(junk) is None

    def test_a_cursor_from_a_different_score_scale_does_not_crash(self):
        assert decode_cursor(encode_cursor(result("0.0"))) is not None
        assert decode_cursor(encode_cursor(result("100.0"))) is not None
