"""Add job_fetch_runs — the fetch budget, rotation state and audit log

Revision ID: 0008_job_fetch_runs
Revises: 0007_applications
Created: 2026-09-07

Needed before the corpus can grow on a schedule. The provider allows a few
hundred requests a month, so the scheduler must know what it has already spent
today — and a count held in memory resets on every container restart, at which
point it fetches again and spends quota that cannot be recovered.

The same rows carry the rotation: asking a provider the same question twice
returns the same jobs, so the only thing that yields new ones is asking one that
has not been asked, and that requires remembering which have.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_job_fetch_runs"
down_revision: str | None = "0007_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_fetch_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("requests_spent", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("scheduled", sa.Boolean(), nullable=False),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_fetch_runs")),
        sa.CheckConstraint(
            "requests_spent >= 0", name=op.f("ck_job_fetch_runs_requests_spent_not_negative")
        ),
    )
    # "What have I spent today?" — asked before every scheduled run.
    op.create_index("ix_job_fetch_runs_started_at", "job_fetch_runs", ["started_at"])
    # "Which query has been left longest?" — the rotation's whole mechanism.
    op.create_index("ix_job_fetch_runs_query", "job_fetch_runs", ["query", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_job_fetch_runs_query", table_name="job_fetch_runs")
    op.drop_index("ix_job_fetch_runs_started_at", table_name="job_fetch_runs")
    op.drop_table("job_fetch_runs")
