"""Jobs provider interface.

Same pattern as ADR-007's LLM abstraction and the email package beside it:
services depend on `JobProvider`, concrete adapters are chosen by configuration,
and tests use a fake. A vendor's field names, status codes and pagination shape
appear in exactly one file — its adapter — and never cross this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class JobPosting:
    """One posting, normalised away from whatever the vendor called things."""

    #: The provider's own stable id, unprefixed. Namespaced by the caller.
    external_id: str
    title: str
    #: **Plain text, and the complete posting.** Not HTML, not a snippet.
    #:
    #: This is the contract that decides whether a provider is usable at all
    #: (ADR-019). `clean_description` does not strip tags, so HTML would put
    #: markup into `description_raw`, break section detection and poison
    #: `content_hash`. And a truncated description has no Requirements heading,
    #: which is the only thing that separates REQUIRED from PREFERRED skills —
    #: so it yields a row that scores against every candidate on no evidence.
    #: An adapter for a provider that returns HTML converts it itself.
    description: str
    #: The provider's apply link, unvalidated — the caller runs `normalize_url`.
    apply_url: str | None
    company_name: str | None
    #: Verbatim, e.g. "Bengaluru, Karnataka, India".
    location: str | None
    #: ISO-3166 alpha-2, or None. Guarded again before it reaches the database.
    country_code: str | None
    posted_at: datetime | None
    #: Only when the provider states one. Synthesising `posted_at + 30 days`
    #: would be inventing a fact about the posting (ADR-012).
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class JobSearchPage:
    postings: list[JobPosting]
    #: Opaque to every caller. None means there are no more pages.
    next_cursor: str | None = None
    #: From the provider's rate-limit headers, when it publishes them.
    quota_remaining: int | None = None


class JobProviderError(RuntimeError):
    """Any failure to obtain a page.

    Deliberately not a taxonomy. The caller makes exactly one decision on the
    difference between this and the quota subclass — "stop and say quota" versus
    "stop and say the provider failed" — so timeouts, DNS failures, 5xx, a
    malformed body and a missing key all collapse into this one.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after


class JobProviderQuotaError(JobProviderError):
    """Rate limited or out of quota — a 429, or whatever the vendor uses."""


@runtime_checkable
class JobProvider(Protocol):
    @property
    def name(self) -> str:
        """Short, stable identifier. It namespaces `external_id`, so changing it
        orphans every row already stored under the old one."""
        ...

    async def search(
        self, *, query: str, country: str, cursor: str | None = None
    ) -> JobSearchPage:
        """One page of results.

        `cursor` is an opaque string this provider produced and the caller only
        ever echoes back. **The caller must never parse it.** That is what keeps
        four incompatible pagination schemes out of the service layer: JSearch's
        `/search` pages by number, `/search-v2` by cursor, Jooble by number, and
        Remotive does not paginate at all.
        """
        ...
