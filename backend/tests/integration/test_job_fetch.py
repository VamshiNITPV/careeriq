"""Live ingestion orchestration (US-3.4), against a fake provider.

Service level, before any endpoint exists, and with no network anywhere:
`FakeJobProvider` imports no HTTP client at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.jobs.base import JobPosting, JobProviderError
from app.integrations.jobs.fake import FakeJobProvider, sample_posting
from app.models.job import Company, Job
from app.services.job.fetch import fetch_and_import
from tests.integration.test_job_import import build_service


async def run(
    session: AsyncSession, provider: FakeJobProvider, *, max_pages: int = 5
) -> object:
    return await fetch_and_import(
        provider=provider,
        service=build_service(session),
        query="python developer",
        country="in",
        max_pages=max_pages,
    )


async def count_jobs(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Job)) or 0)


class TestFetching:
    async def test_ingests_postings_with_their_metadata(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        provider = FakeJobProvider()

        result = await run(db_session, provider)

        assert result.created == 2
        assert result.failed == []
        assert result.stopped_early is False

        job = await db_session.scalar(select(Job).where(Job.external_id == "fake:fake-1"))
        assert job is not None
        assert job.source.value == "PARTNER_API"
        # The namespaced id is what makes "remove everything from provider X"
        # expressible as one query.
        assert job.external_id.startswith("fake:")
        assert job.source_url == "https://jobs.example.com/apply/1"
        # Both of these come from provider metadata. location would otherwise be
        # null (the parser only reads a labelled "Location:" header line, which
        # API prose does not have) and country_code has no parser at all.
        assert job.location == "Bengaluru, Karnataka, India"
        assert job.country_code == "IN"

    async def test_refetching_creates_nothing(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        """US-3.4 AC1. The (source, external_id) check short-circuits before
        parsing, so a re-fetch costs nothing but the request itself."""
        await run(db_session, FakeJobProvider())

        second = await run(db_session, FakeJobProvider())

        assert second.created == 0
        assert second.duplicates == 2
        assert await count_jobs(db_session) == 2

    async def test_a_short_description_is_reported_and_not_stored(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        """US-3.4 AC2, and the reason a truncating provider is unusable.

        A stored-but-unparsed row has no requirements and no skills, and Phase
        6 would still score it against every candidate — a claim about fit made
        on no evidence (ADR-012). It is also the signal that a provider is
        returning snippets: thirty identical failures, not a quietly short
        result.
        """
        short = JobPosting(
            external_id="short",
            title="Engineer",
            description="Too short to be a posting.",
            apply_url="https://jobs.example.com/apply/9",
            company_name="Zeta Labs",
            location="Bengaluru, India",
            country_code="IN",
            posted_at=None,
        )

        result = await run(db_session, FakeJobProvider(pages=[[short]]))

        assert result.created == 0
        assert len(result.failed) == 1
        assert "too short" in result.failed[0].reason.lower()
        assert await count_jobs(db_session) == 0

    @pytest.mark.parametrize("link", [None, "javascript:alert(1)", "not a url"])
    async def test_a_posting_without_a_usable_link_is_skipped(
        self, db_session: AsyncSession, seeded_skills: int, link: str | None
    ) -> None:
        """A live posting's whole advantage over a dataset row is a link that
        works, and `javascript:` is the one route into an href that never
        touches a Pydantic request schema."""
        posting = JobPosting(
            external_id="nolink",
            title=sample_posting(1).title,
            description=sample_posting(1).description,
            apply_url=link,
            company_name="Zeta Labs",
            location="Bengaluru, India",
            country_code="IN",
            posted_at=None,
        )

        result = await run(db_session, FakeJobProvider(pages=[[posting]]))

        assert result.created == 0
        assert "application link" in result.failed[0].reason
        assert await count_jobs(db_session) == 0

    async def test_quota_exhaustion_stops_paging_and_keeps_what_landed(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        """US-3.4 AC3. Retrying would spend a scarce unit to re-ask a question
        that just failed, so the loop stops rather than continuing."""
        provider = FakeJobProvider(
            pages=[[sample_posting(1)], [sample_posting(2)], [sample_posting(3)]],
            quota_error_on_call=2,
        )

        result = await run(db_session, provider)

        assert result.created == 1
        assert result.stopped_early is True
        assert "quota" in (result.stop_reason or "").lower()
        # Exactly two calls: the successful first page and the one that failed.
        # A third would mean the loop carried on after being told to stop.
        assert provider.calls == 2
        assert await count_jobs(db_session) == 1

    async def test_a_provider_failure_reports_rather_than_raising(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        class Broken(FakeJobProvider):
            async def search(self, **kwargs: object) -> object:
                self.calls += 1
                raise JobProviderError("upstream exploded", provider="fake", status_code=502)

        result = await run(db_session, Broken())

        assert result.created == 0
        assert result.stopped_early is True
        assert "failed" in (result.stop_reason or "")

    async def test_a_confidential_employer_becomes_no_company(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        # Otherwise "Confidential" becomes one real company row that dozens of
        # unrelated postings point at, which is worse than none.
        posting = JobPosting(
            external_id="conf",
            title=sample_posting(1).title,
            description=sample_posting(1).description,
            apply_url="https://jobs.example.com/apply/5",
            company_name="Confidential",
            location="Bengaluru, India",
            country_code="IN",
            posted_at=None,
        )

        await run(db_session, FakeJobProvider(pages=[[posting]]))

        # No Company row by that name — that is the whole guarantee. The job may
        # still get a company, because dropping the hint lets the parser read a
        # real name out of the description body, which is the better answer when
        # one is there.
        named = await db_session.scalar(
            select(func.count()).select_from(Company).where(Company.name == "Confidential")
        )
        assert named == 0

    async def test_max_pages_bounds_the_spend(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        # The only guard against an accidental double-fire costing five units
        # instead of one.
        provider = FakeJobProvider(
            pages=[[sample_posting(1)], [sample_posting(2)], [sample_posting(3)]]
        )

        result = await run(db_session, provider, max_pages=1)

        assert provider.calls == 1
        assert result.pages_fetched == 1
        assert result.created == 1
