"""Email provider interface.

Same pattern as ADR-007's LLM abstraction: services depend on `EmailProvider`,
concrete adapters are chosen by configuration, and tests use a fake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None
    # Not every client renders HTML, and some strip it entirely. A text part is
    # required rather than optional so no message can be sent that a plain-text
    # client would show as blank.
    headers: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class EmailProvider(Protocol):
    """Send one message.

    Implementations must not raise on delivery failure. Email is best-effort:
    a registration must not fail because a mail server was briefly unreachable,
    and a password-reset request must not reveal a delivery error to the caller
    (which would leak whether the address exists). Failures are logged and
    reported through the return value.
    """

    async def send(self, message: EmailMessage) -> bool:
        """Return True if the message was accepted for delivery."""
        ...

    @property
    def name(self) -> str: ...
