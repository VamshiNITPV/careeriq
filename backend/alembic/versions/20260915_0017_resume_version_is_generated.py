"""Add resume_versions.is_generated

Revision ID: 0017_resume_version_is_generated
Revises: 0016_optimization_tables
Created: 2026-09-15

Tailoring mints a `resume_versions` row for a document the user never uploaded.
Nothing recorded that, so "the newest version" and "the newest thing the user
gave us" silently stopped being the same row -- and three separate things were
reading the first while meaning the second: which version the resume page opens
by default, which version the list's status pill describes, and which version
the Re-extract button re-parses.

The last of those is the one that matters. Re-parsing a tailored version would
derive profile skills from wording written for a single job application, which
is exactly what `apply_suggestions` avoids by never moving
`resumes.current_version_id`.

Backfilled from the filename, which is the only evidence the existing rows
carry. It is the same fragile signal this column exists to replace, but it is
fragile going *forward* -- for rows already written by a code path that always
used that suffix, it is exact.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_resume_version_is_generated"
down_revision: str | None = "0016_optimization_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_versions",
        sa.Column(
            "is_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Every tailored file written so far was named "<stem>-tailored.<ext>" by
    # apply_suggestions, and nothing else produces that suffix.
    op.execute(
        "UPDATE resume_versions SET is_generated = true "
        "WHERE original_filename LIKE '%-tailored.%'"
    )


def downgrade() -> None:
    op.drop_column("resume_versions", "is_generated")
