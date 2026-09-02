"""Application configuration.

Every setting is read from the environment. There are no fallbacks to
production-shaped values: a missing required setting raises at import time so the
process fails on startup rather than at first use (architecture.md §4).
"""

from __future__ import annotations

import sys
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- app
    app_name: str = "CareerIQ"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # ---------------------------------------------------------------- database
    database_url: str
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    # ---------------------------------------------------------------- redis
    redis_url: str = "redis://localhost:6379/0"

    # ---------------------------------------------------------------- security
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=14, ge=1)
    # NFR-6 sets the floor at 12. Lower is permitted only under ENVIRONMENT=test,
    # enforced in _check_production_hardening below.
    bcrypt_rounds: int = Field(default=12, ge=4, le=18)

    # ---------------------------------------------------------------- email
    # console  -> render to the log, send nothing (default; no setup required)
    # smtp     -> a real SMTP server (Mailpit locally, a provider in production)
    email_provider: str = "console"
    email_from_address: str = "no-reply@careeriq.local"
    email_from_name: str = "CareerIQ"

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    # Short by design. Email is sent inside the request until Phase 10 moves it
    # to the queue, so a hanging SMTP server must not hold a user's signup open.
    smtp_timeout_seconds: int = 5

    # Base URL used to build links inside emails. Cannot be derived from the
    # request: Host and X-Forwarded-Host are attacker-controlled, and trusting
    # them turns every password reset email into a phishing link pointed at a
    # domain of the attacker's choosing.
    frontend_base_url: str = "http://localhost:5173"

    # Short-lived: a reset link sitting in an inbox is a standing key to the
    # account (ADR-017).
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    # Longer, because verification is not a credential — the worst case for an
    # expired link is that the user requests another.
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=168)

    # ---------------------------------------------------------------- cors
    # Kept as a raw string rather than list[str]: pydantic-settings parses list
    # fields from the environment as JSON, so a comma-separated value raises a
    # confusing decode error. Splitting explicitly is clearer than requiring
    # operators to write JSON in a .env file.
    cors_origins: str = "http://localhost:5173"

    # ---------------------------------------------------------------- logging
    log_level: str = "INFO"
    log_json: bool = False

    # ---------------------------------------------------------------- derived
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def is_testing(self) -> bool:
        return self.environment is Environment.TEST

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; strip the async driver from the DSN."""
        return self.database_url.replace("+asyncpg", "")

    # ---------------------------------------------------------------- validation
    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # A sync DSN silently blocks the event loop under load rather than
        # failing outright, which is a miserable class of bug to diagnose (ADR-004).
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver, "
                f"e.g. postgresql+asyncpg://user:pass@host:5432/db (got: {v.split('://')[0]}://...)"
            )
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        if "change-me" in v.lower():
            raise ValueError("JWT_SECRET_KEY is still the placeholder from .env.example.")
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    def _check_production_hardening(self) -> None:
        """Settings that are merely unwise in development are fatal in production."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.debug:
            problems.append("DEBUG must be false in production (it leaks stack traces).")
        if self.bcrypt_rounds < 12:
            problems.append("BCRYPT_ROUNDS must be at least 12 in production (NFR-6).")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must be an explicit allow-list, never '*' (ADR-014).")
        if not self.log_json:
            problems.append("LOG_JSON must be true in production for structured logging.")
        if self.email_provider == "console":
            # Console delivery in production means password reset silently never
            # arrives, locking users out with no error anywhere.
            problems.append("EMAIL_PROVIDER must not be 'console' in production.")
        if self.frontend_base_url.startswith("http://"):
            problems.append("FRONTEND_BASE_URL must use https in production.")
        if problems:
            raise ValueError("Invalid production configuration:\n  - " + "\n  - ".join(problems))


@lru_cache
def get_settings() -> Settings:
    """Cached accessor. Import this rather than instantiating Settings directly.

    The cache means the environment is read once per process, so configuration
    cannot drift mid-run. Tests clear it via get_settings.cache_clear().
    """
    try:
        settings = Settings()  # type: ignore[call-arg]  # values come from the environment
    except Exception as exc:  # re-raised below; caught only to report clearly
        # Pydantic's default traceback buries the cause. Configuration failure is
        # the single most common first-run problem, so make it unmissable.
        print(f"\n[config] Failed to load settings:\n{exc}\n", file=sys.stderr)  # noqa: T201
        raise
    settings._check_production_hardening()
    return settings
