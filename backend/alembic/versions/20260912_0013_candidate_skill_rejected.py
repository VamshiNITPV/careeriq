"""Add candidate_skills.is_rejected — make a removed skill stay removed

Revision ID: 0013_candidate_skill_rejected
Revises: 0012_application_is_saved
Created: 2026-09-12

Removing a skill from a profile deleted the row, which records that the skill is
absent but not that the user *decided* it should be. So any later re-read of the
resume found the term again and put it straight back.

That was reported early — "when I delete the file why those extracted skills will
come again" — and it happened again on 2026-09-12, when re-extracting against a
grown taxonomy returned `Caching`, `Deployment`, `Database Design` and
`Software Engineering` to profiles they had been cleared from. A deletion that
cannot survive the next parse is not really a deletion.

The row now stays and carries the decision. `is_rejected` is the third state
alongside `is_user_verified`, and the CHECK keeps them exclusive: a skill cannot
be both confirmed and refused. Extraction skips rejected rows, profile listings
hide them, and adding the skill back by hand clears the flag — which is the only
way it clears.

**Deleting a *resume* still hard-deletes its skills**, and that difference is
deliberate. Removing one skill is a judgement about the skill; removing the
document takes its derived rows with it, because they no longer have anything to
trace to. Leaving tombstones there would mean re-uploading the same resume
produced nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_candidate_skill_rejected"
down_revision: str | None = "0012_application_is_saved"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_skills",
        sa.Column("is_rejected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Confirmed and refused are contradictory claims about the same row. The API
    # clears one when setting the other; this is the backstop that makes the
    # contradiction unreachable by any writer.
    op.create_check_constraint(
        "verified_or_rejected_not_both",
        "candidate_skills",
        "NOT (is_user_verified AND is_rejected)",
    )
    # No backfill. Rows already deleted left no trace, so the decisions made
    # before this column existed cannot be recovered — including the four
    # re-added on 2026-09-12. Inventing tombstones for them would be guessing at
    # intent, and the user can reject them again in one click.


def downgrade() -> None:
    op.drop_constraint("verified_or_rejected_not_both", "candidate_skills", type_="check")
    op.drop_column("candidate_skills", "is_rejected")
