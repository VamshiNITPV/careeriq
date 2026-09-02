"""Authentication request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import AuthProvider, UserRole

# US-1.1 AC1. Length does the heavy lifting; the character-class rule mainly
# stops "aaaaaaaaaa" style inputs. Deliberately not a maze of complexity rules —
# those push users toward Passw0rd! and a sticky note.
MIN_PASSWORD_LENGTH = 10
# No technical ceiling exists (passwords are SHA-256 pre-hashed before bcrypt),
# but an unbounded field is a free way to make the server do work.
MAX_PASSWORD_LENGTH = 128


def _validate_password_strength(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if not any(c.isalpha() for c in value):
        raise ValueError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit.")
    return value


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "priya@example.com",
                "password": "correct-horse-9",
                "full_name": "Priya S.",
            }
        }
    )

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    # No strength validation here. Rejecting a weak password at login would tell
    # an attacker their guess failed a format check rather than a credential
    # check, and would lock out accounts created under older rules.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class TokenPair(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIs...",
                "refresh_token": "kJ8x2Qw...",
                "token_type": "bearer",
                "expires_in": 1800,
            }
        }
    )

    access_token: str
    refresh_token: str
    # noqa: the linter flags any assignment to a name containing "token" as a
    # hardcoded credential. This is the OAuth 2.0 token_type value, not a secret.
    token_type: str = "bearer"  # noqa: S105
    expires_in: int = Field(description="Access token lifetime in seconds.")


class UserRead(BaseModel):
    """Public representation of a user.

    Note what is absent: password_hash and oauth_subject. This schema is the
    boundary that keeps them absent.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    auth_provider: AuthProvider
    is_active: bool
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class AuthResponse(BaseModel):
    """Returned by register and login."""

    user: UserRead
    tokens: TokenPair
