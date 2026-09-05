"""Pull postings from a jobs provider into the corpus (US-3.4).

A module-level coroutine rather than a class: this composes two things that
already exist — a `JobProvider` and `JobService.submit()` — and owns no state of
its own. Everything about parsing, deduplication, company resolution and skill
extraction is `submit()`'s job, and this deliberately does not reimplement any
of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.integrations.jobs.base import (
    JobPosting,
    JobProvider,
    JobProviderError,
    JobProviderQuotaError,
)
from app.models.enums import JobSource
from app.schemas.job import MAX_JOB_URL
from app.schemas.urls import normalize_url
from app.services.job.pipeline import UnparseableJobError
from app.services.job.service import ImportFailure, JobService, is_duplicate_row

log = get_logger(__name__)

#: `external_id` is String(200) and carries a "provider:" prefix, so the vendor
#: portion is truncated well short of it. An over-length value is a DataError on
#: flush, which the savepoint contains but which costs the posting for no reason.
MAX_VENDOR_ID = 180

#: Employer names that are not employers. `_resolve_company` creates one row per
#: distinct normalised name, so left alone these become a single fake company
#: with dozens of unrelated jobs pointing at it — worse than no company at all,
#: because it fragments the "same employer" signal near-duplicate detection uses.
_NOT_A_COMPANY = re.compile(
    r"^(confidential|company confidential|not disclosed|undisclosed|n/?a|none)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FetchResult:
    provider: str
    created: int
    duplicates: int
    failed: list[ImportFailure]
    pages_fetched: int
    postings_seen: int
    stopped_early: bool
    stop_reason: str | None
    quota_remaining: int | None

    @property
    def processed(self) -> int:
        return self.created + self.duplicates + len(self.failed)


def _company_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or _NOT_A_COMPANY.match(cleaned):
        return None
    return cleaned


def _apply_url(posting: JobPosting) -> str | None:
    """The provider's link, run through the same guard the submit path uses.

    Called explicitly because fetched postings never pass through a Pydantic
    request schema — without this a provider-supplied `javascript:` URL would
    reach an href by a route that bypasses schemas/urls.py entirely.

    The `is None` check is load-bearing: `normalize_url(None, required=True)`
    returns None rather than raising, because its "not a string" branch
    short-circuits before the required check. Relying on the exception alone
    would let a linkless posting straight through.
    """
    try:
        return normalize_url(posting.apply_url, max_length=MAX_JOB_URL, required=True)
    except ValueError:
        return None


async def fetch_and_import(
    *,
    provider: JobProvider,
    service: JobService,
    query: str,
    country: str,
    max_pages: int,
) -> FetchResult:
    """Fetch up to `max_pages` pages and ingest what parses.

    Two failure scopes, deliberately different:

    * **Per posting** — collected and the loop continues, exactly as
      `import_batch` does. A posting that will not parse, or has no usable
      application link, is reported with a reason and **no row is written**.
      Storing it unparsed would put a row into the corpus with no requirements
      and no skills that Phase 6 would still score against every candidate.
    * **Per page** — stop immediately and report what was already ingested.
      `import_batch`'s "collect and continue" does not transfer here: the next
      page request will fail identically and may still be counted against a
      quota, so retrying inside the loop spends a scarce resource to re-ask a
      question that just failed.
    """
    created = 0
    duplicates = 0
    failures: list[ImportFailure] = []
    pages_fetched = 0
    postings_seen = 0
    stop_reason: str | None = None
    quota_remaining: int | None = None
    cursor: str | None = None

    for page_number in range(1, max_pages + 1):
        try:
            page = await provider.search(query=query, country=country, cursor=cursor)
        except JobProviderQuotaError as exc:
            stop_reason = (
                f"Provider quota exhausted after {pages_fetched} page(s)."
                + (f" Retry after {exc.retry_after}s." if exc.retry_after else "")
            )
            break
        except JobProviderError as exc:
            stop_reason = f"Provider request failed on page {page_number}: {exc.message}"
            break

        pages_fetched += 1
        if page.quota_remaining is not None:
            quota_remaining = page.quota_remaining

        for posting in page.postings:
            index = postings_seen
            postings_seen += 1

            apply_url = _apply_url(posting)
            if apply_url is None:
                # Cheapest rejection, so it goes first. Unlike an imported
                # dataset row, a live posting's whole advantage is a working
                # link — without one it is a worse dataset row that also goes
                # stale, and nobody hand-repairs hundreds of them.
                failures.append(
                    ImportFailure(
                        index=index,
                        external_id=posting.external_id,
                        reason="No usable application link.",
                    )
                )
                continue

            try:
                # One savepoint per posting. Provider data has arbitrary ids and
                # employer names, so a failure that reaches the database is a
                # real possibility here — and without this it would poison the
                # session for every posting after it.
                async with service.jobs.savepoint():
                    result = await service.submit(
                        raw_text=posting.description,
                        title=posting.title,
                        company_name=_company_name(posting.company_name),
                        source_url=apply_url,
                        location=posting.location,
                        country_code=posting.country_code,
                        source=JobSource.PARTNER_API,
                        external_id=f"{provider.name}:{posting.external_id[:MAX_VENDOR_ID]}",
                        posted_at=posting.posted_at,
                        expires_at=posting.expires_at,
                    )
                if result.is_duplicate:
                    duplicates += 1
                else:
                    created += 1
            except IntegrityError as exc:
                # A unique violation is two fetches racing on the same
                # (source, external_id) — a duplicate. Anything else is a real
                # failure, and calling it a duplicate would tell the operator
                # the corpus already had a posting that was never written.
                if is_duplicate_row(exc):
                    duplicates += 1
                else:
                    log.exception("fetched posting violated a constraint", index=index)
                    failures.append(
                        ImportFailure(
                            index=index,
                            external_id=posting.external_id,
                            reason="Rejected by the database.",
                        )
                    )
            except UnparseableJobError as exc:
                failures.append(
                    ImportFailure(
                        index=index, external_id=posting.external_id, reason=exc.message
                    )
                )
            except Exception as exc:
                log.exception("fetched posting failed", index=index, provider=provider.name)
                failures.append(
                    ImportFailure(
                        index=index,
                        external_id=posting.external_id,
                        reason=f"Unexpected error: {type(exc).__name__}",
                    )
                )

        cursor = page.next_cursor
        if cursor is None:
            break

    log.info(
        "job fetch finished",
        provider=provider.name,
        query=query,
        country=country,
        pages_fetched=pages_fetched,
        postings_seen=postings_seen,
        created=created,
        duplicates=duplicates,
        failed=len(failures),
        quota_remaining=quota_remaining,
        stop_reason=stop_reason,
    )

    return FetchResult(
        provider=provider.name,
        created=created,
        duplicates=duplicates,
        failed=failures,
        pages_fetched=pages_fetched,
        postings_seen=postings_seen,
        stopped_early=stop_reason is not None,
        stop_reason=stop_reason,
        quota_remaining=quota_remaining,
    )
