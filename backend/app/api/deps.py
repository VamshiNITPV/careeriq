"""Shared FastAPI dependencies.

Wiring only. Anything here that starts making decisions belongs in a service.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import (
    AuthenticationError,
    InvalidTokenError,
    PermissionDeniedError,
)
from app.core.security import decode_access_token
from app.integrations.email import get_email_provider
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import ProfileRepository, UserRepository
from app.repositories.verification import VerificationTokenRepository
from app.services.auth import AuthService
from app.services.notifications import NotificationService

# auto_error=False so a missing header raises our own AuthenticationError and
# produces the standard error envelope, rather than FastAPI's default 403 body
# which would be the one response in the API with a different shape.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------- repositories
def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


def get_profile_repository(session: DbSession) -> ProfileRepository:
    return ProfileRepository(session)


def get_refresh_token_repository(session: DbSession) -> RefreshTokenRepository:
    return RefreshTokenRepository(session)


def get_verification_token_repository(session: DbSession) -> VerificationTokenRepository:
    return VerificationTokenRepository(session)


# ---------------------------------------------------------------- services
def get_notification_service() -> NotificationService:
    # The provider is chosen by configuration and cached per process; tests
    # override this dependency with a capturing provider.
    return NotificationService(get_email_provider())


def get_auth_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    profiles: Annotated[ProfileRepository, Depends(get_profile_repository)],
    refresh_tokens: Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)],
    verification_tokens: Annotated[
        VerificationTokenRepository, Depends(get_verification_token_repository)
    ],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> AuthService:
    return AuthService(
        users=users,
        profiles=profiles,
        refresh_tokens=refresh_tokens,
        verification_tokens=verification_tokens,
        notifications=notifications,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# ---------------------------------------------------------------- current user
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """Resolve the authenticated user from the bearer token.

    The database lookup on every request is deliberate. A JWT alone would be
    cheaper, but it cannot express that an account was deactivated or deleted a
    minute ago — the token stays valid for its full 30 minutes. Access tokens
    are short-lived precisely so this stays a single indexed primary-key read.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication credentials were not provided.")

    payload = decode_access_token(credentials.credentials)

    user = await users.get(payload.subject)
    if user is None:
        # Signature was valid but the account is gone. Same error as a bad
        # token: the client's remedy is identical either way.
        raise InvalidTokenError()

    if not user.is_active:
        raise AuthenticationError("This account is not active.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    """Role gate for admin-only routes.

    403 is correct here, unlike ownership checks which must return 404: the
    caller already knows the endpoint exists, so there is nothing to leak
    (api.md section 1.3).
    """
    if not user.is_admin:
        raise PermissionDeniedError()
    return user


AdminUser = Annotated[User, Depends(require_admin)]


# ---------------------------------------------------------------- request context
def get_client_ip(request: Request) -> str | None:
    """Best-effort client IP for the refresh token audit trail.

    X-Forwarded-For is trusted only because the app sits behind a known proxy
    (Cloud Run). Exposed directly it is client-controlled and must not be used
    for anything security-critical — here it is audit metadata, not a control.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
