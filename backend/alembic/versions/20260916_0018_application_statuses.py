"""Add the remaining application_status members (US-7.1 AC1)

Revision ID: 0018_application_statuses
Revises: 0017_resume_version_is_generated
Created: 2026-09-16

US-7.0 shipped two statuses and left the other five for the event log that
records moving between them. This adds them.

**Separate from 0019, and run outside the transaction.** PostgreSQL will not let
a value added by `ALTER TYPE ... ADD VALUE` be *used* in the same transaction
that added it, and 0019's CHECK constraints name the new members. Two migrations
is not enough on its own -- Alembic wraps the whole upgrade in one transaction by
default -- so the ALTER runs inside `autocommit_block`, which commits it before
anything else reads it.

Found by it failing exactly that way: `UnsafeNewEnumValueUsageError: unsafe use
of new value "REJECTED"`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_application_statuses"
down_revision: str | None = "0017_resume_version_is_generated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: In funnel order, after the two that already exist.
NEW_STATUSES = ("ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN")


def upgrade() -> None:
    # Committed before 0019 runs, which is the whole point of the block.
    with op.get_context().autocommit_block():
        for value in NEW_STATUSES:
            # IF NOT EXISTS so a re-run is harmless; there is no way to remove
            # one, so an interrupted upgrade must be safe to repeat.
            op.execute(f"ALTER TYPE application_status ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Deliberately does nothing.

    PostgreSQL cannot remove a value from an enum. The honest alternatives are
    to recreate the type and rewrite every column that uses it -- which would
    destroy any row already holding one of these -- or to leave the values in
    place, unused, which is what this does. 0019's constraints and table are
    what a downgrade actually needs to undo, and those it does undo.
    """
