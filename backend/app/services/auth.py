"""Authentication business logic.

This module owns the rules. It knows nothing about HTTP — no `Request`, no
status codes, no FastAPI imports (architecture.md section 2). Errors are raised
from the application hierarchy and translated to responses at the API boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    InvalidTokenError,
    RegistrationFailedError,
    TokenReuseError,
)
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    refresh_token_expiry,
    verify_password,
)
from app.models.enums import AuthProvider
from app.models.profile import Profile
from app.models.user import RefreshToken, User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import ProfileRepository, UserRepository
from app.schemas.auth import TokenPair

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A real bcrypt hash of a value nobody can supply.

    Used to equalise the cost of a login attempt for a non-existent account.
    Without it, "no such user" returns in microseconds while a wrong password
    takes the full bcrypt cost, and the difference is a reliable oracle for
    enumerating registered emails.

    Cached because computing it costs the same as a real hash, and it never
    changes within a process.
    """
    return hash_password("this-value-is-never-a-real-password-" + uuid.uuid4().hex)


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        profiles: ProfileRepository,
        refresh_tokens: RefreshTokenRepository,
    ) -> None:
        self.users = users
        self.profiles = profiles
        self.refresh_tokens = refresh_tokens

    # ---------------------------------------------------------------- register
    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, TokenPair]:
        # Checked here for a clean error, but the unique index is the actual
        # guarantee — two concurrent registrations both pass this check.
        if await self.users.email_exists(email):
            log.info("registration rejected: email already exists", email=email)
            raise RegistrationFailedError()

        user = User(
            id=uuid7(),
            email=email,
            password_hash=hash_password(password),
            auth_provider=AuthProvider.LOCAL,
        )
        self.users.add(user)

        # Created eagerly so every downstream feature can assume a profile
        # exists, rather than each one handling the None case.
        self.profiles.add(Profile(id=uuid7(), user_id=user.id, full_name=full_name))

        try:
            await self.users.flush()
        except IntegrityError as exc:
            # Lost the race against a concurrent registration. Same opaque error
            # as above so the endpoint cannot be used to probe for accounts.
            log.info("registration rejected: integrity violation", error=str(exc))
            raise RegistrationFailedError() from exc

        tokens = await self._issue_token_pair(
            user, family_id=uuid7(), user_agent=user_agent, ip_address=ip_address
        )
        log.info("user registered", user_id=str(user.id))
        return user, tokens

    # ---------------------------------------------------------------- login
    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, TokenPair]:
        user = await self.users.get_by_email(email)

        if user is None or user.password_hash is None:
            # Burn equivalent CPU so the response time does not reveal whether
            # the account exists (see _dummy_password_hash).
            verify_password(password, _dummy_password_hash())
            log.info("login failed: no such account", email=email)
            raise AuthenticationError()

        if not verify_password(password, user.password_hash):
            log.info("login failed: bad password", user_id=str(user.id))
            raise AuthenticationError()

        if not user.is_active:
            # Same generic error: a distinct "account disabled" message confirms
            # the address is registered.
            log.info("login failed: inactive account", user_id=str(user.id))
            raise AuthenticationError()

        # Transparently upgrade the stored hash if the configured cost has been
        # raised since this password was last set.
        if needs_rehash(user.password_hash):
            await self.users.update_password_hash(user.id, hash_password(password))
            log.info("password hash upgraded", user_id=str(user.id))

        await self.users.touch_last_login(user.id)

        tokens = await self._issue_token_pair(
            user, family_id=uuid7(), user_agent=user_agent, ip_address=ip_address
        )
        log.info("user logged in", user_id=str(user.id))
        return user, tokens

    # ---------------------------------------------------------------- refresh
    async def refresh(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, TokenPair]:
        """Rotate a refresh token, detecting reuse (US-1.3 AC2)."""
        stored = await self.refresh_tokens.get_by_hash(hash_token(refresh_token))

        if stored is None:
            raise InvalidTokenError()

        if stored.is_revoked:
            # This token was already rotated away. Either it was stolen and the
            # thief is using it, or it was stolen and the legitimate user has
            # since rotated. We cannot tell which, and in both cases somebody
            # untrusted holds a token in this family, so the family dies.
            revoked = await self.refresh_tokens.revoke_family(stored.family_id)

            # Commit before raising. The request's session dependency rolls back
            # on exception, which would otherwise undo the revocation we just
            # made — leaving the attacker's tokens live while the response
            # claims the session was invalidated. This is the deliberate
            # exception to the rule that services do not manage transactions.
            await self.refresh_tokens.commit()

            log.warning(
                "refresh token reuse detected; family revoked",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
                tokens_revoked=revoked,
            )
            raise TokenReuseError()

        if stored.is_expired():
            raise InvalidTokenError("The refresh token has expired.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError()

        # New token joins the same family, so the chain stays linked.
        tokens = await self._issue_token_pair(
            user,
            family_id=stored.family_id,
            user_agent=user_agent,
            ip_address=ip_address,
            replaces=stored,
        )
        log.info("refresh token rotated", user_id=str(user.id))
        return user, tokens

    # ---------------------------------------------------------------- logout
    async def logout(self, *, refresh_token: str) -> None:
        """Revoke the presented token (US-1.3 AC3).

        Returns normally when the token is unknown or already revoked. Logout is
        idempotent, and reporting "that token does not exist" would be another
        existence oracle.
        """
        stored = await self.refresh_tokens.get_by_hash(hash_token(refresh_token))
        if stored is not None and not stored.is_revoked:
            await self.refresh_tokens.revoke(stored)
            log.info("user logged out", user_id=str(stored.user_id))

    # ---------------------------------------------------------------- password
    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if user.password_hash is None or not verify_password(current_password, user.password_hash):
            log.info("password change failed: bad current password", user_id=str(user.id))
            raise AuthenticationError("Current password is incorrect.")

        await self.users.update_password_hash(user.id, hash_password(new_password))

        # Every existing session dies. If the password was changed because it
        # was compromised, leaving other sessions alive defeats the point.
        revoked = await self.refresh_tokens.revoke_all_for_user(user.id)
        log.info("password changed", user_id=str(user.id), sessions_revoked=revoked)

    # ---------------------------------------------------------------- internals
    async def _issue_token_pair(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        user_agent: str | None,
        ip_address: str | None,
        replaces: RefreshToken | None = None,
    ) -> TokenPair:
        settings = get_settings()

        access_token = create_access_token(subject=user.id, role=user.role.value)
        plaintext, token_hash = generate_refresh_token()

        new_token = RefreshToken(
            id=uuid7(),
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=refresh_token_expiry(),
            user_agent=user_agent[:500] if user_agent else None,
            ip_address=ip_address,
        )
        self.refresh_tokens.add(new_token)

        # The INSERT must reach the database before the old row can point at it.
        # `replaced_by_id` is a plain column rather than a declared relationship,
        # so SQLAlchemy's unit of work does not know the two writes are ordered
        # and will happily emit the UPDATE first, violating the self-referential
        # foreign key. Flushing here makes the dependency explicit.
        await self.refresh_tokens.flush()

        if replaces is not None:
            await self.refresh_tokens.revoke(replaces, replaced_by_id=new_token.id)
            await self.refresh_tokens.flush()

        return TokenPair(
            access_token=access_token,
            refresh_token=plaintext,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    @staticmethod
    def is_token_expired(token: RefreshToken) -> bool:
        return token.expires_at <= datetime.now(UTC)
