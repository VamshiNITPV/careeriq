"""User and refresh token models (database.md sections 3.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AuthProvider, UserRole

if TYPE_CHECKING:
    from app.models.profile import Profile


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Native PostgreSQL enum that persists member values, not member names.

    SQLAlchemy defaults to storing `.name`. Our enums define value == name, so
    the two agree today, but being explicit means a future member whose value
    differs cannot silently change what lands in the column.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
        create_type=False,  # types are created explicitly by the migration
    )


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authentication record.

    Deliberately minimal — everything descriptive lives on `Profile`. Keeping
    the row narrow means the table read on every authenticated request stays
    small and cache-friendly.
    """

    __tablename__ = "users"

    # CITEXT rather than lower(email): a functional unique index works, but then
    # every lookup must remember to lower-case its argument. CITEXT makes
    # correct behaviour the default (database.md section 3.1).
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)

    # Null for OAuth-only accounts; the check constraint below enforces that an
    # account always has some usable credential.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    auth_provider: Mapped[AuthProvider] = mapped_column(
        _pg_enum(AuthProvider, "auth_provider"),
        nullable=False,
        default=AuthProvider.LOCAL,
        server_default=AuthProvider.LOCAL.value,
    )
    oauth_subject: Mapped[str | None] = mapped_column(Text, nullable=True)

    role: Mapped[UserRole] = mapped_column(
        _pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped[Profile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        # No eager load: a user accumulates tokens over time and nothing that
        # reads a User for authentication needs them.
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint(
            "(auth_provider = 'LOCAL' AND password_hash IS NOT NULL) "
            "OR (auth_provider <> 'LOCAL' AND oauth_subject IS NOT NULL)",
            name="auth_credential_present",
        ),
        # Partial: two OAuth-less local accounts must not collide on NULL.
        Index(
            "ux_users_oauth",
            "auth_provider",
            "oauth_subject",
            unique=True,
            postgresql_where=text("oauth_subject IS NOT NULL"),
        ),
    )

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


class RefreshToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A single issued refresh token.

    Rows are append-only apart from `revoked_at` and `replaced_by_id`, hence
    CreatedAtMixin rather than TimestampMixin.

    Rotation works as a family: each refresh issues a new token carrying the same
    `family_id` and marks the old one revoked. Presenting an already-revoked
    token means it leaked or a client raced, so the entire family is revoked
    (US-1.3 AC2). Without `family_id` we could only revoke the single stolen
    token, leaving the thief's newer one valid.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # SHA-256 hex of the token. The plaintext is shown to the client once and
    # never stored (security.py module docstring).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Audit context. Useful when a user reports a session they do not recognise.
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="joined")

    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_family_id", "family_id"),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at

    def is_usable(self, *, now: datetime | None = None) -> bool:
        return not self.is_revoked and not self.is_expired(now=now)
