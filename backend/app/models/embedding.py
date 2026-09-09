"""Stored vectors for jobs and candidates (database.md section 3.4)."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

#: Fixed by the column type — pgvector requires a declared dimension, so this is
#: baked into the migration and cannot be changed by configuration alone.
#: Switching to a model of a different width is a migration, and a deliberate
#: one (database.md section 6, Q1).
EMBEDDING_DIMENSIONS = 768


class _EmbeddingColumns:
    """The shape both tables share.

    `model_name` and `model_version` are part of the unique key rather than mere
    metadata: changing embedding models makes existing vectors meaningless, so
    the two generations must be able to coexist on the same subject while a
    backfill runs. Without that, search goes blank the moment a model changes
    (ADR-007).
    """

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: SHA-256 of the document version marker plus the exact document text. What
    #: lets an indexing pass over unchanged text cost no model time at all.
    source_text_hash: Mapped[str] = mapped_column(Text, nullable=False)


class JobEmbedding(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, _EmbeddingColumns):
    """One document vector for one job, under one model generation.

    `CreatedAtMixin` rather than `TimestampMixin`, matching database.md — but
    note what it means here: a re-embed UPDATEs the row in place and resets
    `created_at` to now(). It records when *this vector* was produced, not when
    the row first appeared. That is what makes the staleness predicate in the
    indexer (`jobs.updated_at > job_embeddings.created_at`) correct rather than
    merely plausible.
    """

    __tablename__ = "job_embeddings"

    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("ux_job_embeddings", "job_id", "model_name", "model_version", unique=True),
        Index(
            "ix_job_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class CandidateEmbedding(Base, UUIDPrimaryKeyMixin, CreatedAtMixin, _EmbeddingColumns):
    """One document vector for one resume version.

    Keyed to a version rather than a user because the version is what a match is
    attributable to — `job_matches.resume_version_id` records which resume
    produced a score, and a vector that could not be traced back to one would
    make that unanswerable.
    """

    __tablename__ = "candidate_embeddings"

    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_candidate_embeddings",
            "resume_version_id",
            "model_name",
            "model_version",
            unique=True,
        ),
        Index(
            "ix_candidate_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
