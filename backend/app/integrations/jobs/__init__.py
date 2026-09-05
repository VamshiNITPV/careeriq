"""Live job ingestion, behind a provider interface (ADR-007, ADR-019)."""

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.jobs.base import (
    JobPosting,
    JobProvider,
    JobProviderError,
    JobProviderQuotaError,
    JobSearchPage,
)
from app.integrations.jobs.fake import FakeJobProvider

log = get_logger(__name__)

__all__ = [
    "FakeJobProvider",
    "JobPosting",
    "JobProvider",
    "JobProviderError",
    "JobProviderQuotaError",
    "JobSearchPage",
    "get_job_provider",
]


@lru_cache(maxsize=1)
def get_job_provider() -> JobProvider | None:
    """Build the configured provider once per process, or None if there is none.

    Caching the provider *object* is safe because it holds only configuration.
    An adapter must not cache an `httpx.AsyncClient` on itself: a client binds
    to whichever event loop first touches it, and a process-cached one then
    fails on every later loop.

    `None` rather than a fallback, which is the deliberate difference from
    `get_email_provider`. Falling back to console email costs a log line;
    falling back to anything here would write invented postings into a shared
    corpus. Unconfigured means the endpoint answers 503 and writes nothing.
    """
    settings = get_settings()

    if settings.jobs_provider == "jsearch":
        from app.integrations.jobs.jsearch import JSearchJobProvider

        return JSearchJobProvider(
            api_key=settings.jobs_api_key,
            api_host=settings.jobs_api_host,
            base_url=settings.jobs_api_base_url,
            timeout_seconds=settings.jobs_api_timeout_seconds,
        )

    if settings.jobs_provider == "fake":
        log.warning("job provider is 'fake' — any postings ingested are SYNTHETIC")
        return FakeJobProvider()

    return None
