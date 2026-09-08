"""Add refresh_tokens.last_used_at — the idle session timeout

Revision ID: 0009_refresh_token_last_used_at
Revises: 0008_job_fetch_runs
Created: 2026-09-08

Sessions had absolute lifetimes only: a 30-minute access token and a 14-day
refresh token, with nothing anywhere recording activity. A laptop left open, or
a refresh token copied out of the browser, stayed usable for a fortnight.

This column is what `/auth/refresh` reads to refuse a session that has gone
unused for longer than SESSION_IDLE_TIMEOUT_MINUTES (US-1.3 AC4). It is written
once, at issue: a rotation creates a new row, and the old row's `revoked_at`
already records when it was consumed.

**Deploying this signs people out.** Existing rows are backfilled from
`created_at`, which is the only activity record that exists — so any session
whose token was issued more than the window ago, and has not rotated since, is
refused on its next refresh. Backfilling from `now()` instead would hand every
existing session a fresh hour, which is the wrong direction for a security
control to fail in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_refresh_token_last_used_at"
down_revision: str | None = "0008_job_fetch_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added nullable, backfilled, then tightened. Adding it NOT NULL in one step
    # would need a server_default to invent an activity record for every
    # existing row — precisely the value this must not be allowed to guess.
    op.add_column(
        "refresh_tokens",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE refresh_tokens SET last_used_at = created_at WHERE last_used_at IS NULL")
    op.alter_column(
        "refresh_tokens",
        "last_used_at",
        nullable=False,
        server_default=sa.func.now(),
    )
    # No index. It is only ever read on a row already located by the unique
    # token_hash index, never as a predicate — an index would be write
    # amplification on a column written at every rotation. `expires_at` is
    # unindexed for the same reason.
    #
    # And no CHECK (last_used_at >= created_at): created_at is func.now(), which
    # PostgreSQL evaluates as transaction start on the database clock, while
    # last_used_at comes from the application's datetime.now(UTC). Any skew
    # between the two flips it, and logins start failing on a constraint that
    # protects nothing.


def downgrade() -> None:
    op.drop_column("refresh_tokens", "last_used_at")
