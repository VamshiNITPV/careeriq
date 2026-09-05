"""`JobService.import_batch` against a live database.

At the service level rather than through `POST /admin/jobs/import`, because the
behaviour under test is only reachable from below. `JobImportRecord` caps every
string field, so a value long enough to break at the database is rejected by the
schema first and the request never gets near the session. `import_batch` itself
takes `list[dict[str, object]]` — the schema is the router's concern, not the
service's — and the fetch path (US-3.4) feeds it provider data that never passes
through a request schema at all.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.repositories.job import CompanyRepository, JobRepository, JobSkillRepository
from app.repositories.skill import SkillRepository
from app.services.job.service import JobService
from tests.api.test_jobs import posting


def build_service(session: AsyncSession) -> JobService:
    return JobService(
        jobs=JobRepository(session),
        companies=CompanyRepository(session),
        job_skills=JobSkillRepository(session),
        skills=SkillRepository(session),
    )


class TestStructuredMetadata:
    async def test_supplied_location_and_country_beat_the_parser(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        """Fixes a filter that has never matched anything.

        `country_code` had no writer at all — not in submit(), not anywhere —
        while `GET /jobs?country_code=` filtered on it and documented it. Every
        row in the corpus has NULL, so the filter has always returned zero.
        """
        result = await build_service(db_session).import_batch(
            [
                {
                    "external_id": "loc-1",
                    "description": posting(title="Engineer A"),
                    # The description says "Location: Bengaluru, India (Hybrid)",
                    # so this also pins supplied-wins-over-parsed.
                    "location": "Hyderabad, Telangana, India",
                    "country_code": "in",
                }
            ]
        )
        assert result.created == 1

        job = await db_session.scalar(select(Job).where(Job.external_id == "loc-1"))
        assert job is not None
        assert job.location == "Hyderabad, Telangana, India"
        assert job.country_code == "IN"

    async def test_an_unusable_country_code_is_dropped_not_raised(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        # country_code_is_iso3166 is a CHECK constraint, so a bad value would be
        # an IntegrityError mid-flush — which is a poisoned session, not a
        # clean per-record failure.
        result = await build_service(db_session).import_batch(
            [
                {
                    "external_id": "loc-2",
                    "description": posting(title="Engineer B"),
                    "country_code": "India",
                }
            ]
        )

        assert result.created == 1
        job = await db_session.scalar(select(Job).where(Job.external_id == "loc-2"))
        assert job is not None
        assert job.country_code is None


class TestImportBatchFailureIsolation:
    async def test_a_database_error_does_not_take_the_batch_with_it(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        """US-3.3 AC2, for the half a bare try/except does not deliver.

        A record that fails *before* the flush — too short to parse — is caught
        cleanly either way. A record that fails *inside* it leaves the session
        in a failed state, and without a per-record savepoint every later record
        then dies of PendingRollbackError. `external_id` is String(200), so 300
        characters is a DataError the moment it reaches Postgres.
        """
        records: list[dict[str, object]] = [
            {"external_id": "ok-1", "description": posting(title="Engineer A")},
            {"external_id": "x" * 300, "description": posting(title="Engineer B")},
            {"external_id": "ok-2", "description": posting(title="Engineer C")},
            {"external_id": "ok-3", "description": posting(title="Engineer D")},
        ]

        result = await build_service(db_session).import_batch(records)

        # The two records *after* the bad one are the point. Without the
        # savepoint this is created == 1 with three failures.
        assert result.created == 3
        assert len(result.failed) == 1
        assert result.failed[0].index == 1
        assert result.processed == 4

    async def test_the_session_is_still_usable_afterwards(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        # The failure mode this guards against is not a wrong count, it is a
        # poisoned session: the request would go on to 500 at commit, long after
        # import_batch returned a report that looked fine.
        await build_service(db_session).import_batch(
            [{"external_id": "y" * 300, "description": posting(title="Engineer A")}]
        )

        second = await build_service(db_session).import_batch(
            [{"external_id": "ok-1", "description": posting(title="Engineer B")}]
        )

        assert second.created == 1
