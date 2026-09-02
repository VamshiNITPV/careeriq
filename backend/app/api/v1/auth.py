"""Authentication endpoints (api.md section 2.1).

Routers translate HTTP to service calls and back. No business rules live here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    AuthServiceDep,
    CurrentUser,
    get_client_ip,
    get_user_agent,
)
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserRead,
    VerifyEmailRequest,
)
from app.schemas.common import ErrorResponse, MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])

ClientIp = Annotated[str | None, Depends(get_client_ip)]
UserAgent = Annotated[str | None, Depends(get_user_agent)]

_AUTH_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Invalid or missing credentials"},
}


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses={
        409: {
            "model": ErrorResponse,
            "description": (
                "Registration could not be completed. Deliberately does not "
                "distinguish a duplicate email from other failures (US-1.1 AC3)."
            ),
        },
        422: {"model": ErrorResponse, "description": "Password does not meet policy"},
    },
)
async def register(
    payload: RegisterRequest,
    service: AuthServiceDep,
    ip: ClientIp,
    agent: UserAgent,
) -> AuthResponse:
    user, tokens = await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        user_agent=agent,
        ip_address=ip,
    )
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Exchange credentials for tokens",
    responses=_AUTH_ERRORS,
)
async def login(
    payload: LoginRequest,
    service: AuthServiceDep,
    ip: ClientIp,
    agent: UserAgent,
) -> AuthResponse:
    user, tokens = await service.login(
        email=payload.email,
        password=payload.password,
        user_agent=agent,
        ip_address=ip,
    )
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate a refresh token",
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "Token invalid, expired, or reused. A reused token revokes the "
                "entire rotation family (US-1.3 AC2)."
            ),
        }
    },
)
async def refresh(
    payload: RefreshRequest,
    service: AuthServiceDep,
    ip: ClientIp,
    agent: UserAgent,
) -> TokenPair:
    _, tokens = await service.refresh(
        refresh_token=payload.refresh_token,
        user_agent=agent,
        ip_address=ip,
    )
    return tokens


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke a refresh token",
)
async def logout(payload: LogoutRequest, service: AuthServiceDep) -> MessageResponse:
    # Idempotent by design: an unknown or already-revoked token still returns
    # success, so this endpoint cannot be used to test whether a token is valid.
    await service.logout(refresh_token=payload.refresh_token)
    return MessageResponse(message="Signed out.")


@router.get(
    "/me",
    response_model=UserRead,
    summary="Current authenticated user",
    responses=_AUTH_ERRORS,
)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password and revoke all sessions",
    responses=_AUTH_ERRORS,
)
async def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    service: AuthServiceDep,
    request: Request,
) -> MessageResponse:
    await service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return MessageResponse(message="Password changed. All other sessions have been signed out.")


# ---------------------------------------------------------------- recovery
@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset link",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    service: AuthServiceDep,
    ip: ClientIp,
    agent: UserAgent,
) -> MessageResponse:
    """Always returns 200 with the same message.

    A different response for a registered address would make this endpoint an
    account-existence oracle, undoing the care taken in register and login to
    avoid exactly that. The caller cannot tell whether an email was sent.
    """
    await service.request_password_reset(email=payload.email, ip_address=ip, user_agent=agent)
    return MessageResponse(
        message="If an account exists for that address, a reset link is on its way."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Set a new password using a reset link",
    responses={
        401: {
            "model": ErrorResponse,
            "description": "The link is invalid, expired, or already used",
        },
        422: {"model": ErrorResponse, "description": "Password does not meet policy"},
    },
)
async def reset_password(payload: ResetPasswordRequest, service: AuthServiceDep) -> MessageResponse:
    await service.reset_password(token=payload.token, new_password=payload.new_password)
    return MessageResponse(
        message="Password updated. You have been signed out of all devices — please sign in again."
    )


# ---------------------------------------------------------------- verification
@router.post(
    "/verify-email",
    response_model=UserRead,
    summary="Confirm an email address",
    responses={401: {"model": ErrorResponse, "description": "The link is invalid or expired"}},
)
async def verify_email(payload: VerifyEmailRequest, service: AuthServiceDep) -> UserRead:
    # Unauthenticated on purpose: the link is often opened in a different
    # browser from the one that registered, or on a phone.
    user = await service.verify_email(token=payload.token)
    return UserRead.model_validate(user)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Send the confirmation email again",
    responses=_AUTH_ERRORS,
)
async def resend_verification(
    user: CurrentUser,
    service: AuthServiceDep,
    ip: ClientIp,
    agent: UserAgent,
) -> MessageResponse:
    # Requires a session, so unlike forgot-password there is nothing to
    # enumerate — the caller has already proved who they are.
    await service.resend_verification(user=user, ip_address=ip, user_agent=agent)
    return MessageResponse(message="Confirmation email sent.")
