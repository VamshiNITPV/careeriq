"""Tests for password hashing and token handling.

Security code is the wrong place to rely on "it looked right in review". Each
test below corresponds to a specific claim made in app/core/security.py or in
docs (NFR-6, US-1.3).
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError
from app.core.ids import uuid7
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)

PASSWORD = "correct-horse-battery-staple-9"


class TestPasswordHashing:
    def test_hash_does_not_contain_plaintext(self) -> None:
        assert PASSWORD not in hash_password(PASSWORD)

    def test_correct_password_verifies(self) -> None:
        assert verify_password(PASSWORD, hash_password(PASSWORD)) is True

    def test_wrong_password_rejected(self) -> None:
        assert verify_password("not-the-password", hash_password(PASSWORD)) is False

    def test_same_password_hashes_differently(self) -> None:
        # Distinct salts. Identical hashes would mean an attacker could tell
        # which users share a password.
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_uses_configured_cost_factor(self) -> None:
        cost = int(hash_password(PASSWORD).split("$")[2])
        assert cost == get_settings().bcrypt_rounds
        assert cost >= 12, "NFR-6 requires a bcrypt cost of at least 12"

    def test_empty_password_still_hashes(self) -> None:
        # Length is a validation concern at the schema boundary, not here.
        # This must not raise.
        assert verify_password("", hash_password("")) is True


class TestBcrypt72ByteLimit:
    """The reason for SHA-256 pre-hashing (see security.py module docstring)."""

    def test_bytes_beyond_72_are_significant(self) -> None:
        base = "a" * 72
        stored = hash_password(base + "AAAA")

        # With raw bcrypt both of these would verify, because input is truncated
        # at 72 bytes. Pre-hashing means every byte counts.
        assert verify_password(base + "AAAA", stored) is True
        assert verify_password(base + "ZZZZ", stored) is False

    def test_very_long_passphrase_roundtrips(self) -> None:
        long_password = "correct horse battery staple " * 20  # 580 chars
        assert verify_password(long_password, hash_password(long_password)) is True

    def test_multibyte_unicode_password(self) -> None:
        # Emoji and CJK are multi-byte in UTF-8 and would hit the 72-byte limit
        # far sooner than the character count suggests.
        password = "पासवर्ड-🔐-密碼-" * 5
        assert verify_password(password, hash_password(password)) is True


class TestVerifyPasswordRobustness:
    @pytest.mark.parametrize(
        "bad_hash",
        ["", "not-a-hash", "$2b$", "$2b$12$tooshort", "null"],
    )
    def test_malformed_hash_returns_false_not_raises(self, bad_hash: str) -> None:
        # A corrupted row must fail authentication, not 500 the login endpoint.
        assert verify_password(PASSWORD, bad_hash) is False


class TestNeedsRehash:
    def test_current_cost_does_not_need_rehash(self) -> None:
        assert needs_rehash(hash_password(PASSWORD)) is False

    def test_weaker_cost_needs_rehash(self) -> None:
        weak = hash_password(PASSWORD).replace(
            f"$2b${get_settings().bcrypt_rounds:02d}$", "$2b$04$"
        )
        assert needs_rehash(weak) is True

    def test_unparseable_hash_needs_rehash(self) -> None:
        assert needs_rehash("garbage") is True


class TestAccessTokens:
    def test_roundtrip_preserves_subject_and_role(self) -> None:
        subject = uuid7()
        payload = decode_access_token(create_access_token(subject=subject, role="ADMIN"))

        assert payload.subject == subject
        assert payload.role == "ADMIN"

    def test_expiry_matches_configured_lifetime(self) -> None:
        payload = decode_access_token(create_access_token(subject=uuid7(), role="USER"))
        lifetime = payload.expires_at - payload.issued_at

        assert lifetime == timedelta(minutes=get_settings().access_token_expire_minutes)

    def test_each_token_has_a_unique_jti(self) -> None:
        subject = uuid7()
        a = decode_access_token(create_access_token(subject=subject, role="USER"))
        b = decode_access_token(create_access_token(subject=subject, role="USER"))

        assert a.jti != b.jti

    def test_expired_token_rejected(self) -> None:
        token = create_access_token(
            subject=uuid7(), role="USER", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    def test_token_signed_with_another_secret_rejected(self) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid7()),
                "role": "ADMIN",
                "type": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            "an-attacker-controlled-secret-that-is-long-enough",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged)

    def test_unsigned_token_rejected(self) -> None:
        """The alg=none attack. PyJWT must not accept an unsigned token."""
        forged = jwt.encode(
            {
                "sub": str(uuid7()),
                "role": "ADMIN",
                "type": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            key="",
            algorithm="none",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged)

    def test_wrong_token_type_rejected(self) -> None:
        """A token of another type must not be usable as an access token."""
        settings = get_settings()
        other = jwt.encode(
            {
                "sub": str(uuid7()),
                "role": "USER",
                "type": "password_reset",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(other)

    def test_token_missing_required_claim_rejected(self) -> None:
        settings = get_settings()
        incomplete = jwt.encode(
            {"sub": str(uuid7()), "type": "access", "exp": int(time.time()) + 3600},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(incomplete)

    def test_non_uuid_subject_rejected(self) -> None:
        settings = get_settings()
        bad = jwt.encode(
            {
                "sub": "1",
                "role": "USER",
                "type": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(bad)

    @pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "not.a.jwt"])
    def test_malformed_token_rejected(self, garbage: str) -> None:
        with pytest.raises(InvalidTokenError):
            decode_access_token(garbage)


class TestRefreshTokens:
    def test_returns_plaintext_and_hash(self) -> None:
        token, token_hash = generate_refresh_token()

        assert token != token_hash
        assert len(token_hash) == 64  # sha256 hex
        assert hash_token(token) == token_hash

    def test_tokens_are_unique(self) -> None:
        assert len({generate_refresh_token()[0] for _ in range(1_000)}) == 1_000

    def test_hash_is_deterministic(self) -> None:
        token, _ = generate_refresh_token()
        assert hash_token(token) == hash_token(token)

    def test_plaintext_not_recoverable_from_hash(self) -> None:
        token, token_hash = generate_refresh_token()
        assert token not in token_hash

    def test_token_is_url_safe(self) -> None:
        # It travels in JSON bodies and may end up in headers; anything
        # requiring escaping is a latent bug.
        token, _ = generate_refresh_token()
        assert all(c.isalnum() or c in "-_" for c in token)


class TestUuidNotConfusedWithSubject:
    def test_uuid4_subject_also_roundtrips(self) -> None:
        # Guards against accidentally coupling token handling to uuid7.
        subject = uuid.uuid4()
        assert decode_access_token(create_access_token(subject=subject, role="USER")).subject == subject
