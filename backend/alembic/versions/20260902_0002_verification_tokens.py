"""Add verification_tokens for password reset and email confirmation

Revision ID: 0002_verification_tokens
Revises: 0001_initial
Created: 2026-09-02

Check constraints use bare names: the metadata naming convention prepends
ck_<table>_ to whatever is supplied (see 0001 for the drift this caused).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_verification_tokens"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE verification_purpose AS ENUM ('PASSWORD_RESET', 'EMAIL_VERIFICATION')"
    )

    op.create_table(
        "verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # SHA-256 hex. Only the hash is stored, so a database leak does not hand
        # over working reset links.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "purpose",
            postgresql.ENUM(name="verification_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", postgresql.INET(), nullable=True),
        sa.Column("requested_user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_verification_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_verification_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_verification_tokens_token_hash"),
    )

    op.create_index(
        "ix_verification_tokens_user_purpose",
        "verification_tokens",
        ["user_id", "purpose"],
    )
    op.create_index(
        "ix_verification_tokens_expires_at", "verification_tokens", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_verification_tokens_expires_at", table_name="verification_tokens")
    op.drop_index("ix_verification_tokens_user_purpose", table_name="verification_tokens")
    op.drop_table("verification_tokens")
    op.execute("DROP TYPE IF EXISTS verification_purpose")
