"""Email delivery, behind a provider interface (ADR-007, ADR-017)."""

from functools import lru_cache

from app.core.config import get_settings
from app.integrations.email.base import EmailMessage, EmailProvider
from app.integrations.email.console import CapturingEmailProvider, ConsoleEmailProvider
from app.integrations.email.smtp import SmtpEmailProvider

__all__ = [
    "CapturingEmailProvider",
    "ConsoleEmailProvider",
    "EmailMessage",
    "EmailProvider",
    "SmtpEmailProvider",
    "get_email_provider",
]


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    """Build the configured provider once per process.

    Cached because the SMTP adapter holds connection settings and there is no
    reason to rebuild it per request. An unknown value falls back to console
    rather than raising — except in production, where the config hardening check
    already refuses `console` outright, so a typo cannot silently disable email.
    """
    settings = get_settings()

    if settings.email_provider == "smtp":
        return SmtpEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            timeout_seconds=settings.smtp_timeout_seconds,
            from_address=settings.email_from_address,
            from_name=settings.email_from_name,
        )

    return ConsoleEmailProvider()
