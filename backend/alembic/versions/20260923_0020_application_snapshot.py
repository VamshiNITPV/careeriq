"""Record which resume was sent and how good the match was (US-7.2 AC2)

Revision ID: 0020_application_snapshot
Revises: 0019_application_events
Created: 2026-09-23

AC2 asks the funnel to slice by resume version and by match-score band. Neither
was answerable, and not because the query was missing: the *facts* were not
recorded anywhere. Applications carried no resume version, and match scores are
computed per request and never stored (ADR-006).

Both are facts about a moment. By the time anybody asks, the resume has been
edited and the corpus has moved, so recomputing answers a different question
than the one asked -- "how well would this match today" rather than "how well
did it match when I sent it". They have to be written down as it happens.

Nullable, and staying nullable. Three ordinary situations produce no value: the
user has uploaded no resume, the vectors do not exist yet, and scoring failed.
Every application written before this migration has neither, which is not a
defect to backfill -- the information is gone -- and the analytics group those
rows under one honest heading rather than dropping them.

**SET NULL, not CASCADE.** database.md section 3.7 already warns that cascading
from a resume would make the funnel "quietly lose data". Deleting last year's
resume must not delete the record that you applied to twelve jobs with it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_application_snapshot"
down_revision = "0019_application_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("resume_version_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("match_score_at_apply", sa.Numeric(5, 2), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_applications_resume_version_id_resume_versions"),
        "applications",
        "resume_versions",
        ["resume_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # The analytics group by this column over one user's applications. Small
    # per user, but the index costs almost nothing and the alternative is a
    # sequential scan that grows with every application anybody ever files.
    op.create_index(
        op.f("ix_applications_resume_version_id"),
        "applications",
        ["resume_version_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_resume_version_id"), table_name="applications")
    op.drop_constraint(
        op.f("fk_applications_resume_version_id_resume_versions"),
        "applications",
        type_="foreignkey",
    )
    op.drop_column("applications", "match_score_at_apply")
    op.drop_column("applications", "resume_version_id")
