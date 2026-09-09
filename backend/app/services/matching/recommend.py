"""Stage two of two-stage retrieval, and the paging over its result (ADR-006).

Recall hands over ~200 postings; this module scores all of them with the same
six-dimension formula `GET /jobs/{id}/match` uses, sorts, and returns one page.

**The scorer is reused verbatim, not reimplemented.** That is not tidiness — it
is the only thing that makes the two surfaces agree. If a job shows 68 in the
recommendations list and 61 on its own page, at least one of them is lying, and
a reader has no way to tell which. One code path makes the question unaskable.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.models.job import Job
from app.services.matching.service import MatchingService, MatchResult


@dataclass(frozen=True, slots=True)
class RankedPage:
    """One page of ranked jobs, and where to resume."""

    items: list[MatchResult]
    next_cursor: str | None


def _sort_key(result: MatchResult) -> tuple[Decimal, str]:
    """Descending score, then ascending job id.

    The id is not decoration. Scores are quantised to one decimal place over a
    200-row set, so ties are ordinary rather than rare — and two rows that
    compare equal have no defined order, which means a row can appear on both
    page one and page two, or on neither. The id makes the order total, and a
    total order is the precondition for any cursor being correct at all.
    """
    return (-result.overall_score, str(result.job_id))


def encode_cursor(result: MatchResult) -> str:
    """The position to resume from, as one opaque token.

    Opaque on purpose, and base64 is what makes it look it. A client that parses
    a cursor ends up depending on the sort key, and the sort key is then frozen
    by clients we cannot see — the precedent `JobSearchPage.next_cursor` already
    sets for provider tokens, applied to our own.

    It encodes the last row's sort key rather than an offset, so inserting or
    re-scoring a job between requests shifts the page boundary by one row rather
    than duplicating or skipping a screenful.
    """
    raw = f"{result.overall_score}:{result.job_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[Decimal, str] | None:
    """The sort key a cursor points at, or `None` if it is not one of ours.

    Never raises. A cursor arrives in a URL, so it is user input and can be
    truncated by a mail client, mangled by a share sheet, or simply invented —
    and none of those are worth a 500. The caller treats `None` as "start from
    the beginning", which is the same answer a first request gets.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        score, job_id = raw.rsplit(":", 1)
        return (-Decimal(score), str(uuid.UUID(job_id)))
    except (ValueError, InvalidOperation, binascii.Error, UnicodeDecodeError):
        return None


async def rank_jobs(
    *,
    service: MatchingService,
    user_id: uuid.UUID,
    resume_version_id: uuid.UUID,
    jobs: list[Job],
    cosines: Mapping[uuid.UUID, Decimal],
    limit: int,
    cursor: str | None = None,
    min_score: Decimal | None = None,
) -> RankedPage:
    """Score every recalled job, then return one page of the ranking.

    `match_many` rather than a loop over `match`, and `cosines` carried through
    from stage one rather than re-queried. Both matter: measured on the real
    corpus, the loop version cost **369 ms median and 535 ms p95** for 200 jobs,
    breaching NFR-2's 500 ms budget, because it made 400 database round trips to
    fetch values it either already had or could have fetched once.

    Scoring the whole recall set before slicing is deliberate, and it is what
    the two-stage design buys: stage one bounds the set at ~200, so the work is
    bounded too, and a page can be cut from a ranking that is already total and
    stable. Paging over an unscored set would leave page two unable to know what
    page one contained.
    """
    scored = await service.match_many(
        user_id=user_id,
        jobs=jobs,
        resume_version_id=resume_version_id,
        cosines=cosines,
    )

    if min_score is not None:
        scored = [result for result in scored if result.overall_score >= min_score]

    scored.sort(key=_sort_key)

    if cursor is not None:
        after = decode_cursor(cursor)
        if after is not None:
            # Strictly after, so the row the cursor names is not served twice.
            scored = [result for result in scored if _sort_key(result) > after]

    page = scored[:limit]
    # A next cursor only when there is genuinely more. Returning one on the last
    # page makes a client fetch an empty response to discover it has finished.
    more = len(scored) > limit
    return RankedPage(items=page, next_cursor=encode_cursor(page[-1]) if more and page else None)
