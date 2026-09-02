"""Refresh token data access.

The queries here implement rotation and reuse detection (US-1.3 AC2). See the
`RefreshToken` model docstring for why families exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.models.user import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Find a token by its SHA-256 hash.

        Returns revoked and expired rows too. The caller must distinguish them:
        a revoked row is the reuse signal, and treating it as "not found" would
        discard exactly the evidence reuse detection depends on.
        """
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke(self, token: RefreshToken, *, replaced_by_id: uuid.UUID | None = None) -> None:
        token.revoked_at = datetime.now(UTC)
        if replaced_by_id is not None:
            token.replaced_by_id = replaced_by_id

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke every unrevoked token in a rotation family.

        Triggered when a revoked token is presented again. Whether that is theft
        or a client race, the safe response is identical: end the whole chain and
        force re-authentication.
        """
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Sign the user out everywhere. Used on password change."""
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def count_active_for_user(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(UTC),
            )
            .with_only_columns(RefreshToken.id)
        )
        return len((await self.session.scalars(stmt)).all())

    async def purge_expired(self, *, older_than: datetime | None = None) -> int:
        """Delete tokens that expired before the cutoff.

        Expired tokens are already unusable, so this is housekeeping, not
        security. Revoked-but-unexpired rows are kept: they are what makes reuse
        detectable for the remainder of their lifetime.
        """
        cutoff = older_than or datetime.now(UTC)
        result = await self.session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        )
        return result.rowcount or 0
