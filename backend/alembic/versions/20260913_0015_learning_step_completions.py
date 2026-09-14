"""Add learning_step_completions — progress that outlives a recomputation

Revision ID: 0015_learning_step_completions
Revises: 0014_skill_is_generic
Created: 2026-09-13

The learning path itself is derived, not stored, for the reason `/skills/gaps`
gives: it is a function of gaps that move when the profile is edited and when the
corpus changes overnight, so a saved copy would be wrong more often than right.

Progress is the opposite. Ticking a step off is a **decision the user made**, and
a decision has to survive the plan being recomputed — otherwise finishing Docker
on Tuesday is undone by Wednesday's job fetch. That is exactly the distinction
`database.md`'s `learning_paths` table blurs by storing both together.

So this table holds only the decision: who finished what, and when. The plan is
rebuilt every request and the ticks are matched onto it by `skill_id`.

Keyed on the skill rather than on a step id, deliberately. A step id would belong
to one generated path, and the path is regenerated constantly — the user's claim
is "I have studied Docker", which is about the skill and remains true whichever
plan it appears in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_learning_step_completions"
down_revision: str | None = "0014_skill_is_generic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_step_completions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT, like applications.job_id: a record of study is the user's
        # history, and deleting a taxonomy entry should not erase it silently.
        sa.Column(
            "skill_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # One row per skill per user, which is what makes the toggle idempotent
    # without a read-then-write a double tap could slip between — the same
    # mechanism the save-a-job toggle relies on.
    op.create_index(
        "ux_learning_step_completions",
        "learning_step_completions",
        ["user_id", "skill_id"],
        unique=True,
    )
    # Not automatic on a foreign key, and RESTRICT makes every DELETE on skills
    # check this table.
    op.create_index(
        op.f("ix_learning_step_completions_skill"), "learning_step_completions", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_learning_step_completions_skill"), "learning_step_completions")
    op.drop_index("ux_learning_step_completions", "learning_step_completions")
    op.drop_table("learning_step_completions")
