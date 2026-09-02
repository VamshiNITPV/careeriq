"""Application exception hierarchy and the single API error envelope.

Every non-2xx response shares one shape (api.md §1.4):

    {"error": {"code": ..., "message": ..., "details": {...}, "correlation_id": ...}}

`code` is a stable constant the frontend switches on; `message` is for humans and
may be reworded freely. Services raise these; the handlers registered in main.py
translate them to responses. Nothing below imports FastAPI — the service layer
must not know about HTTP (architecture.md §2).
"""

from __future__ import annotations

from typing import Any


class CareerIQError(Exception):
    """Base for every expected application error.

    Anything not deriving from this is an unhandled bug and becomes an opaque
    500, with the detail going to logs rather than to the client (ADR-014).
    """

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if code is not None:
            self.code = code
        super().__init__(self.message)


# ---------------------------------------------------------------- 400 / 422
class ValidationError(CareerIQError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The request contains invalid data."


class BadRequestError(CareerIQError):
    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be understood."


# ---------------------------------------------------------------- 401 / 403
class AuthenticationError(CareerIQError):
    status_code = 401
    code = "AUTHENTICATION_FAILED"
    message = "Invalid credentials."


class InvalidTokenError(AuthenticationError):
    code = "INVALID_TOKEN"
    message = "The token is invalid or has expired."


class TokenReuseError(AuthenticationError):
    """A revoked refresh token was presented again.

    Either theft or a client race. Either way the whole token family is revoked
    (US-1.3 AC2), so the response deliberately does not distinguish the two.
    """

    code = "TOKEN_REUSE_DETECTED"
    message = "Session invalidated. Please sign in again."


class PermissionDeniedError(CareerIQError):
    """Role check failure only.

    Ownership failures must raise ResourceNotFoundError instead: returning 403
    for a resource the caller does not own confirms it exists, which lets an
    attacker enumerate ids (US-1.5 AC1, api.md §1.3).
    """

    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


# ---------------------------------------------------------------- 404
class ResourceNotFoundError(CareerIQError):
    status_code = 404
    code = "RESOURCE_NOT_FOUND"
    message = "The requested resource was not found."

    def __init__(
        self,
        resource: str = "Resource",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{resource} not found.", details=details)


# ---------------------------------------------------------------- 409
class ConflictError(CareerIQError):
    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state."


class DuplicateResourceError(ConflictError):
    code = "DUPLICATE_RESOURCE"
    message = "That resource already exists."


class RegistrationFailedError(ConflictError):
    """Registration rejected, without saying why.

    US-1.1 AC3: a distinct "email already registered" message turns the
    registration endpoint into an account-existence oracle. The specific reason
    goes to the logs, not the response.
    """

    code = "REGISTRATION_FAILED"
    message = "Registration could not be completed."


class InvalidStateTransitionError(ConflictError):
    code = "INVALID_STATUS_TRANSITION"
    message = "That status change is not allowed."


# ---------------------------------------------------------------- 413 / 415 / 429
class PayloadTooLargeError(CareerIQError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"
    message = "The uploaded file is too large."


class UnsupportedMediaTypeError(CareerIQError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    message = "That file type is not supported."


class RateLimitExceededError(CareerIQError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please slow down."


# ---------------------------------------------------------------- 503
class ServiceUnavailableError(CareerIQError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "A required service is temporarily unavailable."


def build_error_body(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Construct the response envelope. Single source of truth for its shape."""
    error: dict[str, Any] = {"code": code, "message": message, "details": details or {}}
    if correlation_id:
        error["correlation_id"] = correlation_id
    return {"error": error}
