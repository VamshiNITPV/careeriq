"""One-time verification tokens for password reset and email confirmation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import VerificationPurpose
from app.models.user import User


class VerificationToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A single-use, time-limited token sent by email.

    Only the SHA-256 hash is stored, exactly as for refresh tokens: these are
    high-entropy random values, so a slow hash buys nothing, but storing the
    plaintext would turn a database leak into account takeover for every
    outstanding reset link.

    Append-only apart from `used_at`, hence CreatedAtMixin.
    """

    __tablename__ = "verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    purpose: Mapped[VerificationPurpose] = mapped_column(
        SAEnum(
            VerificationPurpose,
            name="verification_purpose",
            values_callable=lambda e: [m.value for m in e],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set the moment the token is consumed. Single use is the whole point: a
    # reset link forwarded, logged by a mail scanner, or left in browser history
    # must not work a second time.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit only. Never used for authorisation — it is trivially spoofed.
    requested_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    requested_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_verification_tokens_user_purpose", "user_id", "purpose"),
        # Supports pruning expired rows without a sequential scan.
        Index("ix_verification_tokens_expires_at", "expires_at"),
    )

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at

    def is_usable(self, *, now: datetime | None = None) -> bool:
        return not self.is_used and not self.is_expired(now=now)
