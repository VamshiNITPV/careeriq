"""The JSearch adapter, driven through httpx.MockTransport.

No socket is opened. MockTransport is httpx's own in-memory transport — the
same trick as the ASGITransport the API tests run on.

The fixture is a real /search-v2 body, saved from one live call, so these pin
the vendor's actual contract and not its documentation — which matters, because
the documented /search endpoint 404s on v5 and the response shape it describes
is the old one.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.integrations.jobs.base import JobProviderError, JobProviderQuotaError
from app.integrations.jobs.jsearch import JSearchJobProvider

#: A real /search-v2 response, saved from one live call and trimmed to two jobs.
#: These tests pin the *actual* vendor contract rather than its documentation —
#: which matters, because the documented /search endpoint 404s on v5.
FIXTURE = json.loads(
    (pathlib.Path(__file__).parent.parent / "fixtures" / "jsearch_search_v2.json").read_text(
        encoding="utf-8"
    )
)
JOB = FIXTURE["data"]["jobs"][0]


def provider_with(handler: Any) -> JSearchJobProvider:
    """A provider whose every request is answered in memory."""
    return JSearchJobProvider(
        api_key="test-key",
        api_host="jsearch.p.rapidapi.com",
        base_url="https://jsearch.p.rapidapi.com",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def page(jobs: list[Any], cursor: str | None = "NEXT") -> dict[str, Any]:
    """A v5 body. Results are nested under data.jobs with an opaque cursor."""
    return {"status": "OK", "data": {"jobs": jobs, "cursor": cursor}}


def ok(payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers=headers or {})

    return handler


class TestMapping:
    async def test_maps_a_result_onto_a_posting(self) -> None:
        provider = provider_with(
            ok(page([JOB]), {"x-ratelimit-requests-remaining": "197"})
        )

        result = await provider.search(query="python developer", country="in")

        assert len(result.postings) == 1
        posting = result.postings[0]
        # job_uid (24 chars), never job_id — which is ~400 and would not fit
        # external_id's String(200) without a truncation that risks collisions.
        assert posting.external_id == 'K4BQlHLn_O2qB6u3AAAAAA=='
        assert len(posting.external_id) < 100
        assert posting.title == 'Python Backend Developer'
        assert posting.company_name == 'Quest Global'
        assert posting.apply_url == 'https://careers.quest-global.com/global/en/job/P-120209/Python-Backend-Developer'
        # City, region and country joined — the parser cannot read a location
        # out of API prose, so this metadata is the only source.
        assert posting.location == "Bengaluru, Karnataka, IN"
        assert posting.country_code == "IN"
        assert posting.posted_at == datetime(2026, 8, 13, tzinfo=UTC)
        # v5 publishes no expiry, and one is never synthesised from posted_at.
        assert posting.expires_at is None
        # The whole posting, not a snippet — the criterion the provider was
        # chosen on. A truncated one has no Requirements section, and skills
        # would fall back to a whole-text scan.
        assert len(posting.description) > 500
        assert result.quota_remaining == 197

    async def test_sends_the_key_and_the_query(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            seen["params"] = dict(request.url.params)
            seen["path"] = request.url.path
            return httpx.Response(200, json=page([JOB]))

        await provider_with(handler).search(query="python", country="in", cursor="OPAQUE")

        assert seen["headers"]["x-rapidapi-key"] == "test-key"
        assert seen["params"]["country"] == "in"
        # An opaque cursor, echoed back verbatim. v5 retired page numbers.
        assert seen["params"]["cursor"] == "OPAQUE"
        assert seen["path"] == "/search-v2"

    async def test_a_result_missing_required_fields_is_dropped_not_fatal(self) -> None:
        # One malformed entry must not cost the page.
        provider = provider_with(ok(page([{"job_id": "a"}, JOB])))

        result = await provider.search(query="python", country="in")

        assert len(result.postings) == 1

    async def test_a_missing_apply_link_is_not_an_error_here(self) -> None:
        # The adapter reports what the provider said; rejecting a linkless
        # posting is the fetch service's decision, not this layer's.
        provider = provider_with(ok(page([{**JOB, "job_apply_link": None}])))

        result = await provider.search(query="python", country="in")

        assert result.postings[0].apply_url is None

    async def test_an_empty_page_ends_the_walk(self) -> None:
        # Otherwise the caller pages until max_pages, spending quota on nothing.
        result = await provider_with(ok(page([]))).search(query="python", country="in")

        assert result.postings == []
        assert result.next_cursor is None


class TestFailures:
    @pytest.mark.parametrize("status", [429, 403])
    async def test_quota_statuses_raise_the_quota_error(self, status: int) -> None:
        """403 as well as 429: RapidAPI uses it for an exhausted plan, and the
        caller has to stop paging rather than treat it as a transient fault."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"message": "no"}, headers={"retry-after": "60"})

        with pytest.raises(JobProviderQuotaError) as exc:
            await provider_with(handler).search(query="python", country="in")

        assert exc.value.retry_after == 60

    async def test_a_server_error_is_a_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="upstream exploded")

        with pytest.raises(JobProviderError):
            await provider_with(handler).search(query="python", country="in")

    async def test_a_body_that_is_not_json_is_a_provider_error(self) -> None:
        # Not a JSONDecodeError escaping as a 500.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        with pytest.raises(JobProviderError):
            await provider_with(handler).search(query="python", country="in")

    @pytest.mark.parametrize("body", [{"status": "OK"}, {"data": []}, {"data": {"x": 1}}])
    async def test_an_unexpected_shape_is_a_provider_error(self, body: Any) -> None:
        # Not a KeyError. `{"data": []}` is the *old* v1 shape, so this also
        # catches a silent downgrade to the retired endpoint.
        with pytest.raises(JobProviderError):
            await provider_with(ok(body)).search(query="python", country="in")

    async def test_a_transport_failure_is_a_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        with pytest.raises(JobProviderError):
            await provider_with(handler).search(query="python", country="in")
