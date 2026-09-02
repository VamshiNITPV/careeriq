"""Console email provider — renders to the log instead of sending.

The default, so a fresh clone works with no mail server and no account. It is
also what the test suite uses, since asserting on captured messages is far more
useful than asserting that an SMTP call was made.

Rejected in production by the config hardening check: silently not sending
password resets would lock users out with no error anywhere.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.integrations.email.base import EmailMessage

log = get_logger(__name__)


class ConsoleEmailProvider:
    @property
    def name(self) -> str:
        return "console"

    async def send(self, message: EmailMessage) -> bool:
        # The body is logged in full on purpose: during development the reset
        # link in this output is how you complete the flow without a mail
        # server. That is also precisely why this provider is refused in
        # production, where the log would then contain live reset links.
        log.info(
            "email (console provider — not actually sent)",
            to=message.to,
            subject=message.subject,
            body=message.text_body,
        )
        return True


class CapturingEmailProvider:
    """Records messages in memory. Test double."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    @property
    def name(self) -> str:
        return "capturing"

    async def send(self, message: EmailMessage) -> bool:
        self.sent.append(message)
        return True

    def last_to(self, address: str) -> EmailMessage | None:
        for message in reversed(self.sent):
            if message.to == address:
                return message
        return None

    def clear(self) -> None:
        self.sent.clear()
