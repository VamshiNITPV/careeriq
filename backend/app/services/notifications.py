"""Composes and dispatches transactional email.

Sits between the auth service and the email provider so that business logic
never touches message bodies or URL construction.

**Delivery is synchronous for now.** ADR-009 says slow work belongs on a queue,
and email does — but the queue arrives in Phase 10, and shipping password reset
without it would mean shipping no recovery path at all. The interim is bounded:
the SMTP timeout is 5 seconds and `send` never raises, so the worst case is a
signup that takes a few extra seconds and an unsent email that is logged.
Phase 10 replaces the call site, not this module's interface.
"""

from __future__ import annotations

from urllib.parse import quote

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.email import EmailMessage, EmailProvider, templates
from app.models.user import User

log = get_logger(__name__)


class NotificationService:
    def __init__(self, provider: EmailProvider) -> None:
        self._provider = provider

    def _link(self, path: str, token: str) -> str:
        settings = get_settings()
        base = settings.frontend_base_url.rstrip("/")
        # Percent-encoded even though the token alphabet is URL-safe: relying on
        # the current generator's alphabet makes this quietly wrong the day it
        # changes.
        return f"{base}{path}?token={quote(token, safe='')}"

    async def _dispatch(self, *, to: str, rendered: templates.RenderedEmail) -> bool:
        return await self._provider.send(
            EmailMessage(
                to=to,
                subject=rendered.subject,
                text_body=rendered.text,
                html_body=rendered.html,
                # Tells mailbox providers and auto-responders this is
                # transactional, so it does not generate out-of-office replies
                # or get grouped as bulk mail.
                headers={"Auto-Submitted": "auto-generated"},
            )
        )

    async def send_email_verification(self, *, user: User, name: str | None, token: str) -> bool:
        settings = get_settings()
        return await self._dispatch(
            to=user.email,
            rendered=templates.verify_email(
                name=name,
                url=self._link("/verify-email", token),
                ttl_hours=settings.email_verification_ttl_hours,
            ),
        )

    async def send_password_reset(self, *, user: User, name: str | None, token: str) -> bool:
        settings = get_settings()
        return await self._dispatch(
            to=user.email,
            rendered=templates.password_reset(
                name=name,
                url=self._link("/reset-password", token),
                ttl_minutes=settings.password_reset_ttl_minutes,
            ),
        )

    async def send_password_changed(self, *, user: User, name: str | None) -> bool:
        return await self._dispatch(to=user.email, rendered=templates.password_changed(name=name))

    async def send_sessions_revoked(self, *, user: User, name: str | None) -> bool:
        return await self._dispatch(to=user.email, rendered=templates.sessions_revoked(name=name))
