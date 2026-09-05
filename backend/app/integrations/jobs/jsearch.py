"""JSearch (RapidAPI) adapter.

The only file in the codebase that knows this vendor's field names, status
codes, header names or pagination scheme. Everything above it speaks
`JobPosting` / `JobSearchPage` / the two provider exceptions, so replacing the
provider is one new module and one config value (ADR-007, ADR-019).

Chosen on one criterion above all others: it returns the **complete** job
description. Adzuna, Jooble and Careerjet truncate by design — their APIs exist
to send traffic back to the aggregator — and a snippet has no Requirements
heading, which is the only thing separating REQUIRED from PREFERRED skills. A
provider that truncates is not "degraded", it is unusable.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.integrations.jobs.base import (
    JobPosting,
    JobProviderError,
    JobProviderQuotaError,
    JobSearchPage,
)

log = get_logger(__name__)

#: RapidAPI publishes the remaining allowance on every response.
_QUOTA_HEADER = "x-ratelimit-requests-remaining"


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _fallback_id(value: Any) -> str | None:
    """A short, stable id when `job_uid` is absent.

    Hashed rather than truncated: `job_id` runs to ~400 characters and its
    leading bytes are not guaranteed distinct, so slicing it could map two
    postings onto one row.
    """
    text = _text(value)
    return hashlib.sha256(text.encode()).hexdigest()[:32] if text else None


def _moment(value: Any) -> datetime | None:
    """An ISO-8601 instant, or nothing.

    Never raises: a vendor sending a date this cannot read costs one nullable
    column, while an exception here would cost the whole page.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class JSearchJobProvider:
    def __init__(
        self,
        *,
        api_key: str,
        api_host: str,
        base_url: str,
        timeout_seconds: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_host = api_host
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # A seam for tests, which pass httpx.MockTransport so no socket opens.
        # Production leaves it None.
        self._transport = transport
        # No httpx.AsyncClient here on purpose. get_job_provider() caches this
        # object for the process, and a cached client binds to whichever event
        # loop first touches it — then fails on every later one. A fetch makes
        # at most five requests, so building a client per call is free and the
        # bug it avoids is not.

    @property
    def name(self) -> str:
        return "jsearch"

    async def search(
        self, *, query: str, country: str, cursor: str | None = None
    ) -> JobSearchPage:
        # /search-v2, not /search. v5 retired the page-numbered endpoint — the
        # old one now 404s — and paginates with an opaque cursor instead. This
        # is exactly the change JobProvider's opaque-cursor contract exists to
        # absorb: the adapter moved, nothing above it did.
        params = {"query": query, "country": country}
        if cursor is not None:
            params["cursor"] = cursor

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self._base_url}/search-v2",
                    params=params,
                    headers={
                        "X-RapidAPI-Key": self._api_key,
                        "X-RapidAPI-Host": self._api_host,
                    },
                )
        except httpx.HTTPError as exc:
            # Timeouts, DNS failures, connection resets. One class, because the
            # caller's only decision is "stop and say the provider failed".
            #
            # The type name is included because several httpx errors carry an
            # empty message — ReadError and RemoteProtocolError among them — and
            # a report reading "request failed: " tells an operator nothing at
            # all about whether to retry, change the query, or check the key.
            detail = str(exc) or "no detail"
            raise JobProviderError(
                f"{type(exc).__name__}: {detail}", provider=self.name
            ) from exc

        # 403 as well as 429: RapidAPI uses it for an exhausted plan, which is a
        # quota problem wearing a permissions status code.
        if response.status_code in (429, 403):
            retry_after = response.headers.get("retry-after")
            raise JobProviderQuotaError(
                f"Provider returned {response.status_code}.",
                provider=self.name,
                status_code=response.status_code,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )

        if response.status_code >= 400:
            raise JobProviderError(
                f"Provider returned {response.status_code}.",
                provider=self.name,
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise JobProviderError(
                "Provider returned a body that is not JSON.", provider=self.name
            ) from exc

        # v5 nests the results: {"data": {"jobs": [...], "cursor": "..."}}.
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise JobProviderError(
                "Provider returned an unexpected response shape.", provider=self.name
            )

        raw_jobs = data["jobs"]
        postings: list[JobPosting] = []
        for raw in raw_jobs:
            posting = self._to_posting(raw)
            if posting is not None:
                postings.append(posting)

        # Results that all failed to map is a different thing from no results,
        # and silently reporting it as "nothing found" is the worst outcome: a
        # renamed vendor field would produce an empty fetch that spent quota,
        # said nothing was wrong, and left the corpus unchanged.
        if raw_jobs and not postings:
            raise JobProviderError(
                f"All {len(raw_jobs)} results were unusable — the response shape may have changed.",
                provider=self.name,
            )

        # No results means the end, whatever the cursor says — otherwise the
        # caller pages to max_pages spending quota on nothing.
        cursor_out = data.get("cursor")
        next_cursor = cursor_out if postings and isinstance(cursor_out, str) else None

        return JobSearchPage(
            postings=postings,
            next_cursor=next_cursor,
            quota_remaining=_quota(response.headers),
        )

    def _to_posting(self, raw: Any) -> JobPosting | None:
        """One result, or None if it is unusable.

        Dropped rather than raised: one malformed entry must not cost the page.
        Everything is read with `.get()` so a renamed field is a skipped posting
        and a log line, never a KeyError surfacing as a 500.
        """
        if not isinstance(raw, dict):
            return None

        # job_uid, not job_id. `job_id` is ~400 characters in v5 — base64 of the
        # uid plus search context — and `external_id` is String(200), so storing
        # it means truncating, which risks collisions and silently breaks the
        # (source, external_id) idempotency US-3.4 AC1 depends on. `job_uid` is
        # the 24-character Google docid: short, and the stable identity of the
        # posting. The hash is only a fallback if a result ever lacks one.
        external_id = _text(raw.get("job_uid")) or _fallback_id(raw.get("job_id"))
        title = _text(raw.get("job_title"))
        description = _text(raw.get("job_description"))
        if external_id is None or title is None or description is None:
            log.warning(
                "skipping a provider result missing required fields",
                provider=self.name,
                job_id=raw.get("job_id"),
            )
            return None

        city = _text(raw.get("job_city"))
        region = _text(raw.get("job_state"))
        country = _text(raw.get("job_country"))
        location = ", ".join(part for part in (city, region, country) if part) or None

        return JobPosting(
            external_id=external_id,
            title=title,
            description=description,
            apply_url=_text(raw.get("job_apply_link")),
            company_name=_text(raw.get("employer_name")),
            location=location,
            country_code=country.upper() if country and len(country) == 2 else None,
            posted_at=_moment(raw.get("job_posted_at_datetime_utc")),
            # v5 publishes no expiry field at all, so this is always None and
            # fetched rows never age out. Read anyway, in case it returns —
            # but never synthesised from posted_at, which would assert an
            # expiry nobody published (ADR-012).
            expires_at=_moment(raw.get("job_offer_expiration_datetime_utc")),
        )


def _quota(headers: httpx.Headers) -> int | None:
    value = headers.get(_QUOTA_HEADER)
    return int(value) if value is not None and value.lstrip("-").isdigit() else None
