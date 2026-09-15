"""Add optimization_analyses and optimization_suggestions (US-6.1)

Revision ID: 0016_optimization_tables
Revises: 0015_learning_step_completions
Created: 2026-09-15

`database.md` does not specify these; they are designed from `api.md` section
2.7 and from what ADR-012 requires to remain auditable.

The learning path is derived on every request because it is a view of data that
moves. A suggestion is the opposite -- a specific thing a model said at a
specific time -- and the user's accept or reject is a decision about that exact
wording. Regenerating would produce different words, leaving a stored decision
pointing at nothing.

Both foreign keys to `resume_versions` and `jobs` are RESTRICT rather than
CASCADE, deliberately. The resume version is the ground truth every suggestion
was validated against; deleting it would leave rows claiming to be grounded in a
document that no longer exists, which is precisely the audit trail ADR-012 needs
to survive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_optimization_tables"
down_revision: str | None = "0015_learning_step_completions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_STATUS = ("PENDING", "RUNNING", "COMPLETE", "FAILED")
SUGGESTION_DECISION = ("PENDING", "ACCEPTED", "REJECTED")


def upgrade() -> None:
    # The project's convention since 0001: create the type by hand, then
    # reference it with `create_type=False`. A bare `sa.Enum` in a column emits
    # its own CREATE TYPE during create_table, which duplicates this one.
    for type_name, values in (
        ("analysis_status", ANALYSIS_STATUS),
        ("suggestion_decision", SUGGESTION_DECISION),
    ):
        rendered = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {type_name} AS ENUM ({rendered})")

    op.create_table(
        "optimization_analyses",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_version_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("resume_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="analysis_status", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "rejected_by_validator", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("dropped_malformed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A count is a count. Negative would mean the writer miscounted, and a
        # constraint says so at the moment it happens rather than leaving a
        # nonsense number in a report weeks later.
        sa.CheckConstraint("rejected_by_validator >= 0", name="ck_analyses_rejected_non_negative"),
        sa.CheckConstraint("dropped_malformed >= 0", name="ck_analyses_dropped_non_negative"),
        # FAILED must explain itself, like ProcessingStatus. A run that stops
        # with no reason is unusable to the user and to whoever debugs it.
        sa.CheckConstraint(
            "status <> 'FAILED' OR error IS NOT NULL",
            name="ck_analyses_failed_has_reason",
        ),
    )
    # The listing query: this user's analyses, newest first.
    op.create_index(
        op.f("ix_optimization_analyses_user_created"),
        "optimization_analyses",
        ["user_id", sa.text("created_at DESC")],
    )
    # Not automatic on a foreign key, and RESTRICT makes every DELETE on
    # resume_versions and jobs check this table.
    op.create_index(
        op.f("ix_optimization_analyses_resume_version"),
        "optimization_analyses",
        ["resume_version_id"],
    )
    op.create_index(op.f("ix_optimization_analyses_job"), "optimization_analyses", ["job_id"])

    op.create_table(
        "optimization_suggestions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("optimization_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggested", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("grounded_in", postgresql.JSONB(), nullable=True),
        sa.Column(
            "decision",
            postgresql.ENUM(name="suggestion_decision", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "applied_version_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("resume_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A rewrite identical to its source is not a suggestion; it asks a
        # reviewer to decide between two identical things. The parser drops
        # these, and this stops any other writer creating one.
        sa.CheckConstraint("original <> suggested", name="ck_suggestions_actually_differ"),
        # A decision that is not PENDING happened at a time. Without this, an
        # accepted suggestion with no timestamp is indistinguishable from a
        # write that half-completed.
        sa.CheckConstraint(
            "decision = 'PENDING' OR decided_at IS NOT NULL",
            name="ck_suggestions_decided_has_time",
        ),
        # Only an accepted suggestion can have produced a version.
        sa.CheckConstraint(
            "applied_version_id IS NULL OR decision = 'ACCEPTED'",
            name="ck_suggestions_applied_was_accepted",
        ),
    )
    # The read path: one analysis's suggestions in presentation order.
    op.create_index(
        op.f("ix_optimization_suggestions_analysis_position"),
        "optimization_suggestions",
        ["analysis_id", "position"],
    )
    op.create_index(
        op.f("ix_optimization_suggestions_applied_version"),
        "optimization_suggestions",
        ["applied_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_optimization_suggestions_applied_version"), "optimization_suggestions"
    )
    op.drop_index(
        op.f("ix_optimization_suggestions_analysis_position"), "optimization_suggestions"
    )
    op.drop_table("optimization_suggestions")

    op.drop_index(op.f("ix_optimization_analyses_job"), "optimization_analyses")
    op.drop_index(op.f("ix_optimization_analyses_resume_version"), "optimization_analyses")
    op.drop_index(op.f("ix_optimization_analyses_user_created"), "optimization_analyses")
    op.drop_table("optimization_analyses")

    op.execute("DROP TYPE suggestion_decision")
    op.execute("DROP TYPE analysis_status")
