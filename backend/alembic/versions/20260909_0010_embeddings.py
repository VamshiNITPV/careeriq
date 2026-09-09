"""Add job_embeddings and candidate_embeddings — 768-dim vectors with HNSW

Revision ID: 0010_embeddings
Revises: 0009_refresh_token_last_used_at
Created: 2026-09-09

The storage half of Phase 6.1. The `vector` extension is already installed —
0001 creates it, and so does the compose init script for a fresh local volume.

`model_name` and `model_version` are in the unique key rather than being mere
metadata. Changing embedding models makes every existing vector meaningless, so
the two generations have to coexist on the same subject while a backfill runs;
keyed on the owner alone, search would go blank the moment a model changed
(ADR-007, database.md section 3.4).

**No CONCURRENTLY here, deliberately.** database.md's migration notes say HNSW
index creation uses it "once the corpus is non-trivial" — but these tables are
*created* by this revision, so both indexes are built on zero rows and there is
nothing to lock. It would also be actively wrong: CONCURRENTLY cannot run inside
a transaction block and Alembic wraps every revision in one, so it would need an
autocommit escape hatch to solve a problem that does not exist here. The
revision that sentence is really about is a future re-embedding one, which adds
rows to an existing table before indexing them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0010_embeddings"
down_revision: str | None = "0009_refresh_token_last_used_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSIONS = 768


def _embedding_table(name: str, owner_column: str, owner_table: str) -> None:
    """Both tables share one shape, so they share one builder."""
    op.create_table(
        name,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(owner_column, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.SmallInteger(), nullable=False),
        # Skips re-embedding text that has not changed, which is what makes a
        # repeat indexing pass cost nothing.
        sa.Column("source_text_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
        sa.ForeignKeyConstraint(
            [owner_column],
            [f"{owner_table}.id"],
            name=op.f(f"fk_{name}_{owner_column}_{owner_table}"),
            ondelete="CASCADE",
        ),
        # A vector whose declared width disagrees with the column is a row that
        # can never be compared to anything. Cheap to enforce here, and close to
        # impossible to diagnose later.
        #
        # The name is bare on purpose: the naming convention already prefixes
        # `ck_%(table_name)s_`, so a pre-prefixed one yields
        # `ck_job_embeddings_ck_job_embeddings_...` and permanent drift.
        sa.CheckConstraint(f"dimensions = {DIMENSIONS}", name="dimensions_match_column"),
    )
    op.create_index(
        f"ux_{name}", name, [owner_column, "model_name", "model_version"], unique=True
    )
    op.create_index(
        f"ix_{name}_hnsw",
        name,
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    _embedding_table("job_embeddings", "job_id", "jobs")
    _embedding_table("candidate_embeddings", "resume_version_id", "resume_versions")


def downgrade() -> None:
    for name in ("candidate_embeddings", "job_embeddings"):
        op.drop_index(f"ix_{name}_hnsw", table_name=name)
        op.drop_index(f"ux_{name}", table_name=name)
        op.drop_table(name)
