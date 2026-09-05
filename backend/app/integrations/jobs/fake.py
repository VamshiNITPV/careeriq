"""A jobs provider that makes no network calls.

The analogue of `CapturingEmailProvider`: primarily a test double, secondarily
selectable via `JOBS_PROVIDER=fake` to walk the ingestion path end to end
locally without spending quota.

Note the deliberate divergence from the email package: `console` is a safe
*default* there because it only logs. There is no safe default here — anything
that "works" writes synthetic postings into the shared corpus that Phase 6 will
rank real candidates against, which is inventing market data (ADR-012). So the
default is `none`, and this is refused in production by the config hardening
check.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.integrations.jobs.base import (
    JobPosting,
    JobProviderQuotaError,
    JobSearchPage,
)

#: Long enough to clear MIN_DESCRIPTION_CHARS and structured enough that the
#: parser finds sections, because a fixture that cannot be parsed would test the
#: rejection path by accident rather than the ingestion path on purpose.
SAMPLE_DESCRIPTION = """Senior Backend Engineer

About us
Zeta Labs builds payments infrastructure for teams across India and beyond.

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy

Requirements
- 5+ years of professional backend experience
- Strong Python and PostgreSQL

Nice to have
- Exposure to Kubernetes
"""


def sample_posting(index: int) -> JobPosting:
    return JobPosting(
        external_id=f"fake-{index}",
        title=f"Senior Backend Engineer {index}",
        description=SAMPLE_DESCRIPTION.replace("Senior Backend Engineer", f"Engineer {index}", 1),
        apply_url=f"https://jobs.example.com/apply/{index}",
        company_name="Zeta Labs",
        location="Bengaluru, Karnataka, India",
        country_code="IN",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
        expires_at=None,
    )


class FakeJobProvider:
    """Deterministic pages, and a call counter tests assert on.

    The counter is how a test proves the loop *stopped* — that a 403 spent no
    quota, or that paging halted on the first 429 rather than carrying on to
    ask an identical question that would fail identically.
    """

    def __init__(
        self,
        *,
        pages: list[list[JobPosting]] | None = None,
        quota_error_on_call: int | None = None,
        quota_remaining: int | None = 100,
    ) -> None:
        self.pages = pages if pages is not None else [[sample_posting(1), sample_posting(2)]]
        self.quota_error_on_call = quota_error_on_call
        self.quota_remaining = quota_remaining
        self.calls = 0

    @property
    def name(self) -> str:
        return "fake"

    async def search(
        self, *, query: str, country: str, cursor: str | None = None
    ) -> JobSearchPage:
        self.calls += 1
        if self.quota_error_on_call is not None and self.calls >= self.quota_error_on_call:
            raise JobProviderQuotaError(
                "Quota exhausted.", provider=self.name, status_code=429, retry_after=60
            )

        # The cursor is an opaque string as far as every caller is concerned;
        # that this one happens to encode an integer is this fake's business.
        index = int(cursor) if cursor is not None else 0
        if index >= len(self.pages):
            return JobSearchPage(postings=[], next_cursor=None)

        return JobSearchPage(
            postings=list(self.pages[index]),
            next_cursor=str(index + 1) if index + 1 < len(self.pages) else None,
            quota_remaining=self.quota_remaining,
        )
