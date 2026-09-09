"""Nearest-neighbour search over job embeddings."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: One statement, and it **binds no vector at all** — the target is a scalar
#: subquery, so 768 floats never cross the wire in either direction.
#:
#: Neighbours are restricted to the same (model_name, model_version) as the
#: target. Comparing vectors from two different models is not merely inaccurate,
#: it is meaningless, and keying the join this way makes it structurally
#: impossible rather than something to remember.
#:
#: The target row prefers the configured model but falls back to whatever this
#: job actually has, so a job embedded under an older model still has neighbours
#: during a backfill. Recall degrades in that window; results are never wrong.
#:
#: `<=>` is pgvector's cosine distance in [0, 2]. Vectors are stored
#: L2-normalised, so `1 - distance` is the cosine similarity, and ascending
#: distance is descending similarity — hence no DESC on the ORDER BY.
#:
#: **The HNSW index will not be used at this corpus size, and that is fine.** A
#: sequential scan over a few hundred rows is cheaper and the planner knows it.
#: The index exists because it has to be in place before the corpus grows —
#: building it later on a populated table is the slow, locking operation
#: database.md warns about. A test that wants to prove it is usable has to force
#: the planner's hand with `SET LOCAL enable_seqscan = off`.
#:
#: One consequence to know before it is a mystery: once the planner *does* choose
#: HNSW, the relational filters below are applied after the approximate scan, so
#: a small LIMIT over a corpus with many expired postings can return fewer rows
#: than asked for. The remedy then is over-fetching or a higher `hnsw.ef_search`.
_SIMILAR = text("""
    WITH target AS (
        SELECT je.embedding, je.model_name, je.model_version
        FROM job_embeddings je
        WHERE je.job_id = :job_id
        ORDER BY (je.model_name = :model_name) DESC, je.created_at DESC
        LIMIT 1
    )
    SELECT j.id,
           1 - (je.embedding <=> t.embedding) AS similarity,
           t.model_name,
           t.model_version
    FROM job_embeddings je
    CROSS JOIN target t
    JOIN jobs j ON j.id = je.job_id
    WHERE je.model_name = t.model_name
      AND je.model_version = t.model_version
      AND je.job_id <> :job_id
      AND j.status = 'ACTIVE'
      AND (j.expires_at IS NULL OR j.expires_at > now())
      AND 1 - (je.embedding <=> t.embedding) >= :min_similarity
    ORDER BY je.embedding <=> t.embedding
    LIMIT :limit
""")

#: Below this, a "neighbour" is just the nearest thing in a small corpus rather
#: than anything a person would call related. Deliberately low for now: the
#: rescaling that would let this be tuned honestly is part of the scoring step,
#: and picking a confident-looking number before measuring one is the mistake
#: ml.md's evaluation-first rule exists to prevent.
MIN_SIMILARITY = 0.3

#: Whether the target row itself exists — the difference between "nothing is
#: close" and "this posting has not been indexed yet".
_HAS_VECTOR = text("SELECT 1 FROM job_embeddings WHERE job_id = :job_id LIMIT 1")


async def find_similar(
    *,
    session: AsyncSession,
    job_id: uuid.UUID,
    model_name: str,
    limit: int,
) -> tuple[list[tuple[uuid.UUID, float]], str, str] | None:
    """Neighbours of one job, nearest first.

    Returns `None` when this job has no vector at all — which the caller reports
    as PENDING rather than as an empty result, because "not indexed yet" and
    "nothing is similar" are different answers to the user.
    """
    if await session.scalar(_HAS_VECTOR, {"job_id": job_id}) is None:
        return None

    rows = (
        await session.execute(
            _SIMILAR,
            {
                "job_id": job_id,
                "model_name": model_name,
                "limit": limit,
                "min_similarity": MIN_SIMILARITY,
            },
        )
    ).all()

    if not rows:
        # The job has a vector but nothing cleared the floor. The model that
        # produced the target is still worth reporting, so read it directly.
        target = (
            await session.execute(
                text("""
                    SELECT model_name, model_version FROM job_embeddings
                    WHERE job_id = :job_id
                    ORDER BY (model_name = :model_name) DESC, created_at DESC
                    LIMIT 1
                """),
                {"job_id": job_id, "model_name": model_name},
            )
        ).one()
        return [], target[0], target[1]

    return (
        [(row[0], float(row[1])) for row in rows],
        rows[0][2],
        rows[0][3],
    )
