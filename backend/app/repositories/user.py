"""User and profile data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.models.enums import AuthProvider
from app.models.profile import Profile
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Look up by email.

        No `.lower()` call: the column is CITEXT, so comparison is already
        case-insensitive at the database level (database.md section 3.1).
        """
        return await self.session.scalar(select(User).where(User.email == email))

    async def get_by_oauth_subject(self, provider: AuthProvider, subject: str) -> User | None:
        return await self.session.scalar(
            select(User).where(
                User.auth_provider == provider,
                User.oauth_subject == subject,
            )
        )

    async def email_exists(self, email: str) -> bool:
        return await self.exists(email=email)

    async def touch_last_login(self, user_id: uuid.UUID) -> None:
        """Record a successful sign-in.

        A bulk UPDATE rather than loading the object and mutating it: this runs
        on every login and there is no reason to fetch the row first.
        """
        await self.session.execute(
            update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
        )

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )


class ProfileRepository(BaseRepository[Profile]):
    model = Profile

    async def get_by_user_id(self, user_id: uuid.UUID) -> Profile | None:
        return await self.session.scalar(select(Profile).where(Profile.user_id == user_id))
