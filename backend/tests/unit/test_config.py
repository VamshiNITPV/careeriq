"""Tests for configuration loading and validation.

Every validator in config.py exists because the failure it prevents is either
silent or expensive. These tests keep them honest.

`_env_file=None` is passed throughout so the developer's real .env cannot
influence the result — otherwise these tests would pass or fail depending on
whose machine they run on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Environment, Settings

VALID_DB = "postgresql+asyncpg://u:p@localhost:5432/db"
VALID_SECRET = "x" * 64


def build(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": VALID_DB,
        "jwt_secret_key": VALID_SECRET,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestDatabaseUrlValidation:
    def test_accepts_asyncpg_dsn(self) -> None:
        assert build().database_url == VALID_DB

    @pytest.mark.parametrize(
        "dsn",
        [
            "postgresql://u:p@localhost:5432/db",  # sync driver
            "postgresql+psycopg2://u:p@localhost:5432/db",
            "sqlite+aiosqlite:///./test.db",
            "mysql+aiomysql://u:p@localhost/db",
        ],
    )
    def test_rejects_non_asyncpg_dsn(self, dsn: str) -> None:
        # A sync driver does not fail loudly; it blocks the event loop under
        # load, which is a far worse way to find out (ADR-004).
        with pytest.raises(PydanticValidationError, match="asyncpg"):
            build(database_url=dsn)

    def test_sync_url_property_strips_the_async_driver(self) -> None:
        # Alembic runs synchronously and cannot use the asyncpg DSN.
        assert build().sync_database_url == "postgresql://u:p@localhost:5432/db"


class TestJwtSecretValidation:
    def test_rejects_short_secret(self) -> None:
        with pytest.raises(PydanticValidationError, match="at least 32 characters"):
            build(jwt_secret_key="too-short")

    def test_rejects_placeholder_from_env_example(self) -> None:
        with pytest.raises(PydanticValidationError, match="placeholder"):
            build(jwt_secret_key="change-me-generate-a-real-secret-before-running")

    def test_accepts_a_real_secret(self) -> None:
        assert build(jwt_secret_key=VALID_SECRET).jwt_secret_key == VALID_SECRET


class TestCorsParsing:
    def test_splits_comma_separated_origins(self) -> None:
        settings = build(cors_origins="http://a.com,http://b.com")
        assert settings.cors_origin_list == ["http://a.com", "http://b.com"]

    def test_trims_whitespace_and_drops_empties(self) -> None:
        settings = build(cors_origins=" http://a.com , , http://b.com ,")
        assert settings.cors_origin_list == ["http://a.com", "http://b.com"]

    def test_single_origin(self) -> None:
        assert build(cors_origins="http://a.com").cors_origin_list == ["http://a.com"]


class TestLogLevelValidation:
    def test_normalises_to_upper_case(self) -> None:
        assert build(log_level="debug").log_level == "DEBUG"

    def test_rejects_unknown_level(self) -> None:
        with pytest.raises(PydanticValidationError):
            build(log_level="VERBOSE")


class TestBcryptRoundsBounds:
    def test_rejects_absurdly_high_cost(self) -> None:
        # 18 rounds is already ~2s per hash; higher turns login into a DoS
        # against ourselves.
        with pytest.raises(PydanticValidationError):
            build(bcrypt_rounds=25)

    def test_rejects_below_minimum(self) -> None:
        with pytest.raises(PydanticValidationError):
            build(bcrypt_rounds=3)


class TestEnvironmentFlags:
    def test_development_is_not_production(self) -> None:
        settings = build(environment="development")
        assert settings.environment is Environment.DEVELOPMENT
        assert settings.is_production is False

    def test_production_flag(self) -> None:
        assert build(environment="production").is_production is True

    def test_test_flag(self) -> None:
        assert build(environment="test").is_testing is True


class TestProductionHardening:
    """Settings that are merely unwise locally must be fatal in production."""

    def _check(self, **overrides: object) -> None:
        # A baseline that satisfies every rule, so each test can break exactly
        # one thing and see only that failure reported.
        defaults: dict[str, object] = {
            "environment": "production",
            "log_json": True,
            "debug": False,
            "bcrypt_rounds": 12,
            "cors_origins": "https://app.example.com",
            "email_provider": "smtp",
            "frontend_base_url": "https://app.example.com",
            "storage_provider": "gcs",
        }
        build(**{**defaults, **overrides})._check_production_hardening()

    def test_valid_production_config_passes(self) -> None:
        self._check()

    def test_console_email_provider_is_rejected(self) -> None:
        # Console delivery in production means password reset silently never
        # arrives — users locked out with no error logged anywhere.
        with pytest.raises(ValueError, match="EMAIL_PROVIDER"):
            self._check(email_provider="console")

    def test_local_storage_is_rejected(self) -> None:
        # Cloud Run has no persistent disk and scales to zero, so local storage
        # means uploaded resumes disappear when an instance is recycled.
        with pytest.raises(ValueError, match="STORAGE_PROVIDER"):
            self._check(storage_provider="local")

    def test_insecure_frontend_url_is_rejected(self) -> None:
        # Links in emails are built from this value, so http would send every
        # password reset over plaintext.
        with pytest.raises(ValueError, match="FRONTEND_BASE_URL"):
            self._check(frontend_base_url="http://app.example.com")

    def test_debug_true_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="DEBUG must be false"):
            self._check(debug=True)

    def test_weak_bcrypt_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="BCRYPT_ROUNDS"):
            self._check(bcrypt_rounds=8)

    def test_wildcard_cors_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="allow-list"):
            self._check(cors_origins="*")

    def test_non_json_logging_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="LOG_JSON"):
            build(environment="production", log_json=False)._check_production_hardening()

    def test_all_problems_reported_together(self) -> None:
        # Reporting one problem per run turns fixing config into a guessing game.
        with pytest.raises(ValueError) as exc:
            build(
                environment="production",
                debug=True,
                bcrypt_rounds=8,
                cors_origins="*",
                log_json=False,
            )._check_production_hardening()

        message = str(exc.value)
        assert "DEBUG" in message
        assert "BCRYPT_ROUNDS" in message
        assert "allow-list" in message
        assert "LOG_JSON" in message

    def test_development_skips_hardening_checks(self) -> None:
        # Must not raise: DEBUG and readable logs are the point of local dev.
        build(environment="development", debug=True, log_json=False)._check_production_hardening()
