"""Add application_events, and widen the applications constraints (US-7.1)

Revision ID: 0019_application_events
Revises: 0018_application_statuses
Created: 2026-09-16

The immutable log AC2 asks for, plus the two CHECK constraints that 0018's new
statuses invalidate. Both were written when the funnel had two members and are
wrong the moment it has seven:

- `applied_has_timestamp` was `(status = 'APPLIED') = (applied_at IS NOT NULL)`.
  An application that reaches INTERVIEW still has an `applied_at` -- it was
  applied to -- so the left side goes false while the right stays true and the
  row cannot be written at all.
- `saved_or_applied` was `is_saved OR status = 'APPLIED'`. An unbookmarked
  application at ASSESSMENT fails it for the same reason.

The rule they were each expressing still holds; only the vocabulary changed.
`applied_at` is set once an application has actually been sent, and a live row
must still mean *something*.

Terminal statuses are exempt from the timestamp rule rather than required to
carry one. AC1 makes REJECTED and WITHDRAWN reachable from any active state
including SAVED, and a job somebody bookmarked and then withdrew was never
applied to -- inventing a timestamp for it would put a fabricated application
date into the US-7.2 funnel.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_application_events"
down_revision: str | None = "0018_application_statuses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLIED_HAS_TIMESTAMP = """
CASE
    WHEN status = 'SAVED' THEN applied_at IS NULL
    WHEN status IN ('REJECTED', 'WITHDRAWN') THEN true
    ELSE applied_at IS NOT NULL
END
"""

OLD_APPLIED_HAS_TIMESTAMP = "(status = 'APPLIED') = (applied_at IS NOT NULL)"


def upgrade() -> None:
    op.drop_constraint("applied_has_timestamp", "applications", type_="check")
    op.create_check_constraint("applied_has_timestamp", "applications", APPLIED_HAS_TIMESTAMP)

    op.drop_constraint("saved_or_applied", "applications", type_="check")
    op.create_check_constraint(
        "saved_or_applied", "applications", "is_saved OR status <> 'SAVED'"
    )

    op.execute("CREATE TYPE application_event_type AS ENUM ('STATUS_CHANGE')")

    op.create_table(
        "application_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL on the row that records an application being created, because
        # there was no previous status to come from.
        sa.Column("from_status", postgresql.ENUM(name="application_status", create_type=False)),
        sa.Column(
            "to_status",
            postgresql.ENUM(name="application_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            postgresql.ENUM(name="application_event_type", create_type=False),
            nullable=False,
            server_default="STATUS_CHANGE",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # No updated_at. Rows here are never modified -- that is what makes the
        # log worth reading. A correction is a new event, not an edit.
        sa.CheckConstraint("from_status IS NULL OR from_status <> to_status", name="ck_events_move"),
    )
    # The read path: one application's history, oldest first.
    op.create_index(
        op.f("ix_application_events_application_occurred"),
        "application_events",
        ["application_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_application_events_application_occurred"), "application_events")
    op.drop_table("application_events")
    op.execute("DROP TYPE application_event_type")

    op.drop_constraint("saved_or_applied", "applications", type_="check")
    op.create_check_constraint("saved_or_applied", "applications", "is_saved OR status = 'APPLIED'")

    op.drop_constraint("applied_has_timestamp", "applications", type_="check")
    op.create_check_constraint(
        "applied_has_timestamp", "applications", OLD_APPLIED_HAS_TIMESTAMP
    )
