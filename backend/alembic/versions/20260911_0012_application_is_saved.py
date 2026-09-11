"""Add applications.is_saved — separate the bookmark from the funnel stage

Revision ID: 0012_application_is_saved
Revises: 0011_recommendation_feedback
Created: 2026-09-11

`status` held SAVED *or* APPLIED and nothing else, so "I bookmarked this" and
"I applied to this" were the same column holding two mutually exclusive values.
The interface could not tell them apart either: the bookmark icon filled
whenever a row existed, so ticking "I have applied" bookmarked the job on the
user's behalf — reported as a bug, and it was one.

`status` stays what it was designed to be, a funnel stage with ASSESSMENT /
INTERVIEW / OFFER still to come. `is_saved` is the separate fact: did the user
bookmark it. A job can now be either, both, or — once neither — not a row at
all, which is what `saved_or_applied` enforces.

**The backfill is a choice, not a recovery.** The old model never recorded
whether an applied job had also been bookmarked, so that information does not
exist and no backfill can restore it. `is_saved = (status = 'SAVED')` is used
because it matches the Saved list users can already see — `SavedJobs` has always
filtered on `status = 'SAVED'`, so an applied job was already absent from it.
The visible cost is that a job someone applied to loses its filled bookmark;
the alternative, `is_saved = true` for every row, would newly move every applied
job *into* the saved list, inventing bookmarks nobody made. Given the bug being
fixed is the system asserting a bookmark on the user's behalf, inventing more of
them is the wrong direction to fail in.

The downgrade drops the column, which collapses the two facts back into one and
loses every bookmark that was recorded on an applied job. Nothing can be done
about that — it is the information the old schema had no room for.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_application_is_saved"
down_revision: str | None = "0011_recommendation_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default=true so existing rows get a value in one statement; the
    # backfill below then corrects it. The default stays afterwards because the
    # common write really is a bookmark — the repository passes the flag
    # explicitly in every case, so nothing depends on it.
    op.add_column(
        "applications",
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.execute("UPDATE applications SET is_saved = (status = 'SAVED')")

    # Added after the backfill, not before: every APPLIED row is momentarily
    # is_saved = true, which satisfies this anyway, but ordering it this way
    # means the constraint is never checked against a half-migrated table.
    op.create_check_constraint(
        "saved_or_applied",
        "applications",
        "is_saved OR status = 'APPLIED'",
    )


def downgrade() -> None:
    op.drop_constraint("saved_or_applied", "applications", type_="check")
    op.drop_column("applications", "is_saved")
