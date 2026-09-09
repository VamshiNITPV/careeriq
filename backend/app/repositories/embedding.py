"""Vector storage, and the backlog queries that stand in for a queue."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import Insert as PGInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.ids import uuid7
from app.models.embedding import CandidateEmbedding, JobEmbedding
from app.repositories.base import BaseRepository

#: Jobs with no current vector for this model, oldest first.
#:
#: `j.updated_at > je.created_at` is the re-embed trigger. It is deliberately
#: over-eager — attaching a source URL bumps `updated_at` without changing a word
#: of the document — and the indexer corrects for that by comparing
#: `source_text_hash` before any model time is spent.
#:
#: ACTIVE and unexpired only: embedding a DUPLICATE would put a vector in the
#: corpus for a row the search filters out anyway, and an expired posting is not
#: a neighbour anyone wants offered.
_JOB_BACKLOG = text("""
    SELECT j.id
    FROM jobs j
    LEFT JOIN job_embeddings je
           ON je.job_id = j.id
          AND je.model_name = :model_name
          AND je.model_version = :model_version
    WHERE j.status = 'ACTIVE'
      AND (j.expires_at IS NULL OR j.expires_at > now())
      AND (je.id IS NULL OR j.updated_at > je.created_at)
    ORDER BY j.created_at
    LIMIT :limit
""")

#: Resume versions that are *current* for a live resume and finished parsing.
#:
#: `resumes.current_version_id`, not every COMPLETE version: the candidate
#: document is built from the user's live profile and career rows, not from the
#: version's own text, so every version of one resume would produce a
#: byte-identical document and therefore N identical vectors.
#:
#: No staleness predicate here, unlike jobs. The inputs are spread across four
#: user-scoped tables, and a GREATEST over four correlated subqueries is not
#: worth writing at this scale — every eligible row is returned and the hash
#: decides. Add the predicate when the row count makes the difference measurable.
#:
#: The soft-delete filter is load-bearing: without it the worker re-embeds
#: deleted resumes forever.
_CANDIDATE_BACKLOG = text("""
    SELECT r.current_version_id
    FROM resumes r
    JOIN resume_versions v ON v.id = r.current_version_id
    WHERE r.deleted_at IS NULL
      AND v.processing_status = 'COMPLETE'
    ORDER BY v.created_at
    LIMIT :limit
""")


def _upsert(statement: PGInsert, conflict_columns: list[str]) -> PGInsert:
    """One row per (owner, model_name, model_version), replaced in place.

    Idempotent, so two processes racing produce one row rather than an
    IntegrityError. `created_at` is reset on every write, deliberately: it
    records when *this vector* was produced, and the jobs backlog above compares
    `jobs.updated_at` against it to decide staleness.
    """
    return statement.on_conflict_do_update(
        index_elements=conflict_columns,
        set_={
            "embedding": statement.excluded.embedding,
            "dimensions": statement.excluded.dimensions,
            "source_text_hash": statement.excluded.source_text_hash,
            "created_at": func.now(),
        },
    )


class JobEmbeddingRepository(BaseRepository[JobEmbedding]):
    model = JobEmbedding

    async def backlog(self, *, model_name: str, model_version: str, limit: int) -> list[uuid.UUID]:
        rows = await self.session.execute(
            _JOB_BACKLOG,
            {"model_name": model_name, "model_version": model_version, "limit": limit},
        )
        return [row[0] for row in rows.all()]

    async def hash_for(
        self, job_id: uuid.UUID, *, model_name: str, model_version: str
    ) -> str | None:
        """The stored document hash, or None when there is no vector yet.

        Reading only the hash column rather than the row: the vector is 768
        floats and nothing here needs it.
        """
        return await self.session.scalar(
            select(JobEmbedding.source_text_hash).where(
                JobEmbedding.job_id == job_id,
                JobEmbedding.model_name == model_name,
                JobEmbedding.model_version == model_version,
            )
        )

    async def upsert(
        self,
        *,
        job_id: uuid.UUID,
        embedding: list[float],
        model_name: str,
        model_version: str,
        dimensions: int,
        source_text_hash: str,
    ) -> None:
        statement = pg_insert(JobEmbedding).values(
            id=uuid7(),
            job_id=job_id,
            embedding=embedding,
            model_name=model_name,
            model_version=model_version,
            dimensions=dimensions,
            source_text_hash=source_text_hash,
        )
        await self.session.execute(_upsert(statement, ["job_id", "model_name", "model_version"]))


class CandidateEmbeddingRepository(BaseRepository[CandidateEmbedding]):
    model = CandidateEmbedding

    async def backlog(self, *, limit: int) -> list[uuid.UUID]:
        rows = await self.session.execute(_CANDIDATE_BACKLOG, {"limit": limit})
        return [row[0] for row in rows.all()]

    async def hash_for(
        self, resume_version_id: uuid.UUID, *, model_name: str, model_version: str
    ) -> str | None:
        return await self.session.scalar(
            select(CandidateEmbedding.source_text_hash).where(
                CandidateEmbedding.resume_version_id == resume_version_id,
                CandidateEmbedding.model_name == model_name,
                CandidateEmbedding.model_version == model_version,
            )
        )

    async def upsert(
        self,
        *,
        resume_version_id: uuid.UUID,
        embedding: list[float],
        model_name: str,
        model_version: str,
        dimensions: int,
        source_text_hash: str,
    ) -> None:
        statement = pg_insert(CandidateEmbedding).values(
            id=uuid7(),
            resume_version_id=resume_version_id,
            embedding=embedding,
            model_name=model_name,
            model_version=model_version,
            dimensions=dimensions,
            source_text_hash=source_text_hash,
        )
        await self.session.execute(
            _upsert(statement, ["resume_version_id", "model_name", "model_version"])
        )
