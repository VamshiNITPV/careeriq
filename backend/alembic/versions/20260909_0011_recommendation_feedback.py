"""Add recommendation_feedback — relevance labels for a future learned ranker

Revision ID: 0011_recommendation_feedback
Revises: 0010_embeddings
Created: 2026-09-09

Phase 6.3. **Nothing reads this table**, and it ships anyway.

ADR-005's migration path to a learned ranker needs labelled relevance
judgements, and those can only be gathered forward in time: an endpoint added in
Phase 9 starts against an empty table however good the model is by then. The
cheap half of that plan is a table and one endpoint; the expensive half is the
model, and it is not made cheaper by waiting.

`job_id` cascades rather than restricting, unlike `applications`. The two look
similar and are not: an application is historical fact about a person and must
survive the posting, while a relevance label is a statement *about* a posting's
features — once the row is gone, the label describes nothing and cannot be
trained on.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_recommendation_feedback"
down_revision: str | None = "0010_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A fresh CREATE TYPE is safe inside the transaction env.py wraps every
    # migration in; only ALTER TYPE ... ADD VALUE carries the same-transaction
    # restriction (see 0006).
    # The type is `recommendation_rating` while the table is
    # `recommendation_feedback`. They cannot share a name: CREATE TABLE
    # implicitly creates a composite type, so a matching enum collides with it —
    # and PostgreSQL only says so when the table is created, not the type.
    op.execute(
        "CREATE TYPE recommendation_rating AS ENUM "
        "('RELEVANT', 'NOT_RELEVANT', 'NOT_INTERESTED')"
    )

    op.create_table(
        "recommendation_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rating",
            postgresql.ENUM(name="recommendation_rating", create_type=False),
            nullable=False,
        ),
        sa.Column("ranking_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_feedback")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_recommendation_feedback_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_recommendation_feedback_job_id_jobs"),
            ondelete="CASCADE",
        ),
    )

    # One opinion per user per job, updated rather than appended: a history of
    # somebody changing their mind is not a training label. It is also what lets
    # the endpoint be a single idempotent upsert.
    op.create_index(
        "ux_recommendation_feedback",
        "recommendation_feedback",
        ["user_id", "job_id"],
        unique=True,
    )
    op.create_index("ix_recommendation_feedback_job", "recommendation_feedback", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_recommendation_feedback_job", table_name="recommendation_feedback")
    op.drop_index("ux_recommendation_feedback", table_name="recommendation_feedback")
    op.drop_table("recommendation_feedback")
    op.execute("DROP TYPE recommendation_rating")
