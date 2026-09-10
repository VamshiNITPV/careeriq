"""Stage one of two-stage retrieval (ADR-006).

The corpus is scored in two passes because scoring all of it on every request
cannot meet NFR-2. This module is the cheap pass: **one SQL statement** that uses
the pgvector HNSW index to pull the ~200 nearest postings to a candidate's
vector, applying every hard filter in the same statement so the expensive pass
never sees a row it would have thrown away.

`app/services/job/similar.py` is the same query anchored on a *job* instead of a
candidate, and the two deliberately share their shape. Three properties are worth
preserving on purpose rather than by accident:

**No vector is ever bound as a parameter.** The anchor is a CTE, so 768 floats
never cross the wire in either direction.

**Model equality is enforced in the join**, not remembered by a caller. Comparing
vectors from two different models is not merely inaccurate, it is meaningless;
requiring `(model_name, model_version)` to match makes that structurally
impossible. Mid-backfill this yields no rows rather than a confident wrong
number.

**The ORDER BY is the bare `<=>` expression**, because anything else — wrapping
it, negating it, sorting on the derived similarity column — makes the HNSW index
unusable and silently turns this into a sequential scan.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

#: How many postings the cheap pass hands to the expensive one (ADR-006).
#:
#: 200 against the ~20 a user actually sees. The gap is the whole safety margin:
#: stage two can reorder heavily, but it can never recover a job stage one did
#: not return, so recall here bounds the quality of everything downstream. ml.md
#: sets the target at **Recall@200 >= 0.95** and tracks it as a separate metric
#: for exactly that reason — a retrieval failure is invisible in the ranking
#: metrics and looks like bad ranking, which is a long way to debug.
RECALL_LIMIT = 200

#: Multiplier applied to the vector scan before the relational filters bite.
#:
#: This exists because of a specific pgvector behaviour, and it is the main
#: correctness risk in this module. **Once the planner chooses HNSW, the index
#: returns its `ef_search` best matches and the WHERE clause is applied to those
#: rows afterwards.** So a LIMIT of 200 over a corpus where many postings are
#: expired, duplicated, or already applied to comes back with fewer than 200 —
#: quietly, with no error, and the missing rows are exactly the ones stage two
#: would have ranked.
#:
#: Over-fetching is the cheaper of the two remedies (the other is raising
#: `hnsw.ef_search`, which is a session GUC and affects every query on the
#: connection). Three is a starting point, not a measured constant; 6.4's
#: Recall@200 measurement is what will settle it.
OVERFETCH = 3


@dataclass(frozen=True, slots=True)
class RecalledJob:
    """One candidate for ranking, with the cosine that got it here."""

    job_id: uuid.UUID
    similarity: float


#: The recall query.
#:
#: `exclude_applied` is parameterised rather than branched into two SQL strings,
#: so both paths are the same statement and the planner caches one plan.
#:
#: Note what is *not* filtered here: `min_score` is a threshold on the final
#: six-dimension score, which does not exist yet at this point in the pipeline.
#: Filtering on cosine as a proxy would drop jobs whose skill or location
#: dimensions would have carried them, which is precisely the hybrid ranking
#: ADR-005 exists to provide.
#:
#: `:allowed` is the browse filters, arriving as a pre-computed id array rather
#: than as predicates. It sits **inside the `nearest` CTE**, before the LIMIT, so
#: the vector scan itself is restricted — put it in the outer query and the
#: overfetch budget would be spent on rows the filter then throws away. NULL
#: means "no filter", which keeps one statement and one cached plan for both
#: paths rather than branching into two SQL strings.
#:
#: The parameter is **typed via `bindparams` rather than cast inline**. An inline
#: `:allowed::uuid[]` is what this wants to say, and `text()` cannot parse it —
#: SQLAlchemy reads the `::` as part of the parameter name. Declaring the type
#: once says the same thing and lets PostgreSQL resolve `ANY(NULL)`, which it
#: cannot do for an untyped NULL.
_RECALL = text("""
    WITH anchor AS (
        SELECT ce.embedding, ce.model_name, ce.model_version
        FROM candidate_embeddings ce
        WHERE ce.resume_version_id = :resume_version_id
        ORDER BY (ce.model_name = :model_name) DESC, ce.created_at DESC
        LIMIT 1
    ),
    nearest AS (
        SELECT je.job_id,
               je.embedding <=> a.embedding AS distance
        FROM job_embeddings je
        CROSS JOIN anchor a
        WHERE je.model_name = a.model_name
          AND je.model_version = a.model_version
          AND (:allowed IS NULL OR je.job_id = ANY(:allowed))
        ORDER BY je.embedding <=> a.embedding
        LIMIT :overfetch
    )
    SELECT n.job_id, 1 - n.distance AS similarity
    FROM nearest n
    JOIN jobs j ON j.id = n.job_id
    WHERE j.status = 'ACTIVE'
      AND (j.expires_at IS NULL OR j.expires_at > now())
      AND (
        NOT :exclude_applied
        OR NOT EXISTS (
            SELECT 1 FROM applications ap
            WHERE ap.job_id = n.job_id
              AND ap.user_id = :user_id
              AND ap.status = 'APPLIED'
              AND ap.deleted_at IS NULL
        )
      )
    ORDER BY n.distance
    LIMIT :limit
""").bindparams(bindparam("allowed", type_=ARRAY(UUID(as_uuid=True))))

#: Whether this resume has a vector at all — the difference between "nothing is
#: close" and "we have not indexed you yet". `find_similar` draws the same
#: distinction for the same reason: an empty list with no explanation makes a
#: feature that is merely behind look identical to one that is broken.
_HAS_VECTOR = text(
    "SELECT 1 FROM candidate_embeddings WHERE resume_version_id = :resume_version_id LIMIT 1"
)


async def recall_jobs(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    resume_version_id: uuid.UUID,
    model_name: str,
    limit: int = RECALL_LIMIT,
    exclude_applied: bool = True,
    allowed_job_ids: list[uuid.UUID] | None = None,
) -> list[RecalledJob] | None:
    """The ~200 postings nearest this resume, nearest first.

    Returns `None` when the resume has no vector — reported by the caller as
    PENDING rather than as an empty list, because "not indexed yet" and "nothing
    matched" are different answers and only one of them is worth waiting on.

    `allowed_job_ids` restricts recall to a pre-filtered set, which is how the
    browse filters reach a match-sorted list. Pass `None` for no restriction;
    an **empty list means no job qualifies** and short-circuits, because
    `= ANY('{}')` is a round trip that can only return nothing.

    **This restriction is applied after the index, not by it** — see `OVERFETCH`.
    A narrow filter therefore competes with the overfetch budget: at this corpus
    size the planner sequential-scans and the result is exact, but on a corpus
    large enough for HNSW to be chosen, a filter matching few postings can return
    fewer rows than `limit` with nothing reporting that it did. That is the
    filtered-ANN problem and it is not solved here; it is bounded by measurement
    when the corpus is big enough for the measurement to mean anything.
    """
    if await session.scalar(_HAS_VECTOR, {"resume_version_id": resume_version_id}) is None:
        return None

    # Checked after the vector, not before: with no vector *and* an empty filter
    # the honest answer is still "we have not indexed you", which is the one the
    # caller can act on. Returning "nothing matched" would send someone off to
    # widen a filter that was never the problem.
    if allowed_job_ids is not None and not allowed_job_ids:
        return []

    rows = (
        await session.execute(
            _RECALL,
            {
                "resume_version_id": resume_version_id,
                "user_id": user_id,
                "model_name": model_name,
                "limit": limit,
                "overfetch": limit * OVERFETCH,
                "exclude_applied": exclude_applied,
                "allowed": allowed_job_ids,
            },
        )
    ).all()

    return [RecalledJob(job_id=row[0], similarity=float(row[1])) for row in rows]
