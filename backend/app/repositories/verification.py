"""Verification token data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.models.enums import VerificationPurpose
from app.models.verification import VerificationToken
from app.repositories.base import BaseRepository


class VerificationTokenRepository(BaseRepository[VerificationToken]):
    model = VerificationToken

    async def get_by_hash(self, token_hash: str) -> VerificationToken | None:
        """Look up by hash, including used and expired rows.

        The caller must distinguish those cases: they are all rejections, but
        conflating them with "not found" loses the ability to log a replay of a
        consumed reset link, which is a signal worth having.
        """
        return await self.session.scalar(
            select(VerificationToken).where(VerificationToken.token_hash == token_hash)
        )

    async def invalidate_outstanding(self, user_id: uuid.UUID, purpose: VerificationPurpose) -> int:
        """Consume every unused token of this purpose for the user.

        Called before issuing a new one, so requesting a second reset link
        immediately kills the first. Otherwise every request would leave another
        working key to the account sitting in an inbox, and a user clicking
        'resend' three times would have three live links.
        """
        result = await self.session.execute(
            update(VerificationToken)
            .where(
                VerificationToken.user_id == user_id,
                VerificationToken.purpose == purpose,
                VerificationToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def mark_used(self, token: VerificationToken) -> None:
        token.used_at = datetime.now(UTC)

    async def purge_expired(self, *, older_than: datetime | None = None) -> int:
        """Housekeeping. Expired tokens are already unusable."""
        cutoff = older_than or datetime.now(UTC)
        result = await self.session.execute(
            delete(VerificationToken).where(VerificationToken.expires_at < cutoff)
        )
        return result.rowcount or 0
