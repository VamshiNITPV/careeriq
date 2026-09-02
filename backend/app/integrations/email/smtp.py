"""SMTP email provider.

Used with Mailpit locally and with a real relay in deployed environments.
"""

from __future__ import annotations

from email.message import EmailMessage as MimeMessage

import aiosmtplib

from app.core.logging import get_logger
from app.integrations.email.base import EmailMessage

log = get_logger(__name__)


class SmtpEmailProvider:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        use_tls: bool = False,
        timeout_seconds: int = 5,
        from_address: str,
        from_name: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout_seconds
        self._from_address = from_address
        self._from_name = from_name

    @property
    def name(self) -> str:
        return f"smtp://{self._host}:{self._port}"

    def _build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = f"{self._from_name} <{self._from_address}>"
        mime["To"] = message.to
        mime["Subject"] = message.subject
        for key, value in message.headers.items():
            mime[key] = value

        mime.set_content(message.text_body)
        if message.html_body is not None:
            # add_alternative puts HTML *after* the text part, which is what
            # multipart/alternative requires: clients render the last part they
            # understand, so reversing this shows plain text to everyone.
            mime.add_alternative(message.html_body, subtype="html")
        return mime

    async def send(self, message: EmailMessage) -> bool:
        try:
            await aiosmtplib.send(
                self._build(message),
                hostname=self._host,
                port=self._port,
                username=self._username or None,
                password=self._password or None,
                start_tls=self._use_tls or None,
                timeout=self._timeout,
            )
            log.info("email sent", to=message.to, subject=message.subject)
            return True
        except Exception as exc:
            # Never propagates. A mail outage must not fail a registration, and
            # a delivery error must never surface to the caller of
            # forgot-password — that would reveal whether the address exists.
            log.error(
                "email delivery failed",
                to=message.to,
                subject=message.subject,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
