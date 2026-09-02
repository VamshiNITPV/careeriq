"""Authentication business logic.

This module owns the rules. It knows nothing about HTTP — no `Request`, no
status codes, no FastAPI imports (architecture.md section 2). Errors are raised
from the application hierarchy and translated to responses at the API boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
from app.models.enums import AuthProvider, VerificationPurpose
from app.models.profile import Profile
from app.models.user import RefreshToken, User
from app.models.verification import VerificationToken
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import ProfileRepository, UserRepository
from app.repositories.verification import VerificationTokenRepository
from app.schemas.auth import TokenPair
from app.services.notifications import NotificationService

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
        verification_tokens: VerificationTokenRepository,
        notifications: NotificationService,
    ) -> None:
        self.users = users
        self.profiles = profiles
        self.refresh_tokens = refresh_tokens
        self.verification_tokens = verification_tokens
        self.notifications = notifications

    async def _display_name(self, user_id: uuid.UUID) -> str | None:
        """First name for email greetings. Absence is fine — templates handle it."""
        profile = await self.profiles.get_by_user_id(user_id)
        full_name = profile.full_name if profile else None
        return full_name.split()[0] if full_name else None

    async def _issue_verification_token(
        self,
        *,
        user: User,
        purpose: VerificationPurpose,
        ttl: timedelta,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """Create a single-use token and return the plaintext.

        Any outstanding token of the same purpose is consumed first, so a user
        who clicks "resend" three times ends up with one working link rather
        than three live keys to their account sitting in an inbox.
        """
        await self.verification_tokens.invalidate_outstanding(user.id, purpose)

        plaintext, token_hash = generate_refresh_token()
        self.verification_tokens.add(
            VerificationToken(
                id=uuid7(),
                user_id=user.id,
                token_hash=token_hash,
                purpose=purpose,
                expires_at=datetime.now(UTC) + ttl,
                requested_ip=ip_address,
                requested_user_agent=user_agent[:500] if user_agent else None,
            )
        )
        await self.verification_tokens.flush()
        return plaintext

    async def _consume_verification_token(
        self, *, token: str, purpose: VerificationPurpose
    ) -> VerificationToken:
        """Validate and mark a token used, or raise InvalidTokenError.

        Every rejection reason produces the same error. A caller learns only
        that the link did not work — not whether it was expired, already used,
        for a different purpose, or never existed.
        """
        stored = await self.verification_tokens.get_by_hash(hash_token(token))

        if stored is None:
            raise InvalidTokenError("This link is invalid or has expired.")

        if stored.purpose is not purpose:
            # A verification link must not be usable to reset a password: the
            # two have very different lifetimes and consequences.
            log.warning(
                "verification token used for the wrong purpose",
                expected=purpose.value,
                actual=stored.purpose.value,
                user_id=str(stored.user_id),
            )
            raise InvalidTokenError("This link is invalid or has expired.")

        if not stored.is_usable():
            log.info(
                "verification token rejected",
                user_id=str(stored.user_id),
                purpose=purpose.value,
                used=stored.is_used,
                expired=stored.is_expired(),
            )
            raise InvalidTokenError("This link is invalid or has expired.")

        await self.verification_tokens.mark_used(stored)
        return stored

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

        # The account is usable immediately; verification confirms the address
        # rather than gating access. Blocking sign-in until a link is clicked
        # would strand anyone whose email is delayed or filtered, and this is
        # not a system where an unverified address grants anything.
        verification_token = await self._issue_verification_token(
            user=user,
            purpose=VerificationPurpose.EMAIL_VERIFICATION,
            ttl=timedelta(hours=get_settings().email_verification_ttl_hours),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.notifications.send_email_verification(
            user=user, name=full_name.split()[0] if full_name else None, token=verification_token
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

            # Tell the user why they were signed out. Without this the defence
            # is indistinguishable from a bug, and the one person who might
            # recognise the activity as suspicious never hears about it.
            owner = await self.users.get(stored.user_id)
            if owner is not None:
                await self.notifications.send_sessions_revoked(
                    user=owner, name=await self._display_name(owner.id)
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

        # If an attacker changed this password, the notification is the owner's
        # only chance to notice while they can still act.
        await self.notifications.send_password_changed(
            user=user, name=await self._display_name(user.id)
        )

        log.info("password changed", user_id=str(user.id), sessions_revoked=revoked)

    # ---------------------------------------------------------------- recovery
    async def request_password_reset(
        self,
        *,
        email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Send a reset link, if the address belongs to an account.

        Returns None in every case. The endpoint must behave identically for a
        registered and an unregistered address, or it becomes the account
        enumeration oracle that registration and login are carefully built to
        avoid (US-1.1 AC3). No exception, no distinguishing delay, no hint in
        the response.
        """
        user = await self.users.get_by_email(email)

        if user is None:
            log.info("password reset requested for unknown address", email=email)
            return

        if not user.is_active:
            log.info("password reset requested for inactive account", user_id=str(user.id))
            return

        if user.password_hash is None:
            # OAuth-only account: there is no password to reset, and creating
            # one here would silently add a second way into the account.
            log.info("password reset requested for oauth-only account", user_id=str(user.id))
            return

        token = await self._issue_verification_token(
            user=user,
            purpose=VerificationPurpose.PASSWORD_RESET,
            ttl=timedelta(minutes=get_settings().password_reset_ttl_minutes),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.notifications.send_password_reset(
            user=user, name=await self._display_name(user.id), token=token
        )
        log.info("password reset email sent", user_id=str(user.id))

    async def reset_password(self, *, token: str, new_password: str) -> None:
        stored = await self._consume_verification_token(
            token=token, purpose=VerificationPurpose.PASSWORD_RESET
        )

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError("This link is invalid or has expired.")

        await self.users.update_password_hash(user.id, hash_password(new_password))

        # Every session dies. A reset is usually a response to losing control of
        # the account, so leaving existing sessions alive would defeat it.
        revoked = await self.refresh_tokens.revoke_all_for_user(user.id)

        # Completing a reset proves control of the mailbox, which is exactly
        # what verification asks for — so there is no reason to ask again.
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)

        await self.notifications.send_password_changed(
            user=user, name=await self._display_name(user.id)
        )
        log.info("password reset completed", user_id=str(user.id), sessions_revoked=revoked)

    # ---------------------------------------------------------------- verification
    async def verify_email(self, *, token: str) -> User:
        stored = await self._consume_verification_token(
            token=token, purpose=VerificationPurpose.EMAIL_VERIFICATION
        )

        user = await self.users.get(stored.user_id)
        if user is None:
            raise InvalidTokenError("This link is invalid or has expired.")

        # Idempotent: clicking a link twice, or having a mail scanner prefetch
        # it, should not look like a failure to the user.
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
            log.info("email verified", user_id=str(user.id))

        return user

    async def resend_verification(
        self,
        *,
        user: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Re-send the confirmation link to an authenticated user.

        Requires a session, unlike password reset, so there is nothing to
        enumerate — the caller already proved who they are.
        """
        if user.email_verified_at is not None:
            log.info("verification resend skipped; already verified", user_id=str(user.id))
            return

        token = await self._issue_verification_token(
            user=user,
            purpose=VerificationPurpose.EMAIL_VERIFICATION,
            ttl=timedelta(hours=get_settings().email_verification_ttl_hours),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.notifications.send_email_verification(
            user=user, name=await self._display_name(user.id), token=token
        )
        log.info("verification email resent", user_id=str(user.id))

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
