"""Password hashing and token handling.

Two deliberate choices worth reading before changing anything here.

**Passwords are SHA-256 pre-hashed before bcrypt.** bcrypt silently truncates
input at 72 bytes — a 100-character passphrase is only as strong as its first 72
bytes, and the user is never told. Hashing to a fixed 44-byte digest first
removes the limit entirely. (This is the same construction passlib calls
``bcrypt_sha256``.) Base64 is used rather than raw digest bytes because bcrypt
also stops at the first NUL byte, which a raw digest can contain.

**Access tokens are JWTs; refresh tokens are not.** An access token must be
verifiable without a database round trip on every request, which is what a
signed JWT is for. A refresh token must be *revocable* (US-1.3 AC3) and must
support reuse detection (AC2) — both of which require a database lookup anyway.
Given that lookup, a signature buys nothing, so refresh tokens are opaque random
strings stored as SHA-256 hashes. A leaked database therefore yields no usable
refresh tokens.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError

TokenType = Literal["access"]

# 48 bytes -> 64 url-safe characters. Well beyond guessing range.
_REFRESH_TOKEN_BYTES = 48


# ---------------------------------------------------------------- passwords
def _prehash(password: str) -> bytes:
    """SHA-256 then base64, so bcrypt receives a fixed 44-byte NUL-free input."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """Hash a plaintext password. Cost factor comes from BCRYPT_ROUNDS (NFR-6)."""
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed hash: a corrupt row should
    fail authentication, not 500 the endpoint. bcrypt.checkpw is constant-time
    with respect to the hash comparison.
    """
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash uses a weaker cost than currently configured.

    Lets us transparently upgrade hashes at next successful login after raising
    BCRYPT_ROUNDS, instead of leaving old accounts permanently under-protected.
    """
    try:
        cost = int(password_hash.split("$")[2])
    except (IndexError, ValueError):
        return True
    return cost < get_settings().bcrypt_rounds


# ---------------------------------------------------------------- access tokens
@dataclass(frozen=True, slots=True)
class AccessTokenPayload:
    subject: uuid.UUID
    role: str
    jti: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    *,
    subject: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a signed access token (30 min default, US-1.3 AC1)."""
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))

    claims: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        # jti gives us a handle for future denylisting without a schema change.
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessTokenPayload:
    """Verify and decode an access token.

    Raises InvalidTokenError for every failure mode — expired, wrong signature,
    malformed, or wrong token type. The caller gets one exception to handle and
    the client learns nothing about which check failed.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            # Reject a token missing any claim we rely on, rather than
            # discovering it as a KeyError below.
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError() from exc

    # An attacker who obtains any other signed token type must not be able to
    # present it as an access token.
    if claims.get("type") != "access":
        raise InvalidTokenError()

    try:
        subject = uuid.UUID(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError() from exc

    return AccessTokenPayload(
        subject=subject,
        role=claims.get("role", "USER"),
        jti=claims.get("jti", ""),
        issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )


# ---------------------------------------------------------------- refresh tokens
def hash_token(token: str) -> str:
    """SHA-256 of an opaque token, hex encoded.

    Plain SHA-256 rather than bcrypt is correct here: the input is 48 bytes of
    cryptographic randomness, so there is no dictionary to attack and the slow
    hashing bcrypt provides would only add latency to every refresh.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    """Return (plaintext, hash).

    The plaintext goes to the client exactly once. Only the hash is persisted,
    so a database compromise does not hand over usable sessions.
    """
    token = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
    return token, hash_token(token)


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=get_settings().refresh_token_expire_days)
