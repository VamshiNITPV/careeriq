"""What gets recorded when an application is sent (US-7.2 AC2).

A resume is edited and the corpus moves daily, so "which resume did I use and
how well did it match" has no answer unless it was written down as it happened.
These are the tests that it is, and that recording it never costs anything else.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_matching_service
from app.models.application import Application
from tests.api.test_applications import make_job
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API


async def row(session: AsyncSession, job_id: str) -> Application:
    application = await session.scalar(
        select(Application).where(
            Application.job_id == uuid.UUID(job_id), Application.deleted_at.is_(None)
        )
    )
    assert application is not None
    await session.refresh(application)
    return application


class TestApplicationSnapshot:
    async def test_applying_records_the_resume_and_the_score(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        job_id = await make_job(client, auth_headers)
        await upload_resume(client, auth_headers, run_pipeline)

        response = await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": True, "applied": True},
        )

        assert response.status_code == 200, response.text
        saved = await row(db_session, job_id)
        assert saved.resume_version_id is not None
        # A score, not merely a non-null. The five non-semantic dimensions score
        # without any vectors, so this is reachable even unindexed.
        assert saved.match_score_at_apply is not None
        assert saved.match_score_at_apply > 0

    async def test_a_bookmark_records_neither(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The invariant this feature is most likely to break.

        Saved and applied have been conflated here before — marking a job
        applied once silently bookmarked it, which is why the request body
        carries two booleans. A snapshot on a bookmark would put a match score
        in the funnel's band table for a job nothing was ever sent to, and
        inflate the count every rate is divided by.
        """
        job_id = await make_job(client, auth_headers)
        await upload_resume(client, auth_headers, run_pipeline)

        response = await client.put(
            f"{API}/jobs/{job_id}/application", headers=auth_headers, json={}
        )

        assert response.status_code == 200, response.text
        saved = await row(db_session, job_id)
        assert saved.resume_version_id is None
        assert saved.match_score_at_apply is None

    async def test_unapplying_clears_the_snapshot(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The three fields describe one event and must not disagree.

        `applied_at` is already cleared when the mark comes off. A snapshot left
        behind would claim a resume and a score for an application the user has
        just said they did not send.
        """
        job_id = await make_job(client, auth_headers)
        await upload_resume(client, auth_headers, run_pipeline)
        await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": True, "applied": True},
        )

        await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": True, "applied": False},
        )

        saved = await row(db_session, job_id)
        assert saved.applied_at is None
        assert saved.resume_version_id is None
        assert saved.match_score_at_apply is None

    async def test_a_failure_to_score_still_records_the_application(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """Recording *that* you applied must never depend on scoring *how well*.

        This sits inside an idempotent toggle a phone taps twice, and US-7.0's
        whole design is that the write is cheap and repeatable. Failing the
        request because a cosine threw would lose the fact the user was actually
        trying to record, to protect a number that is analytics garnish.
        """
        job_id = await make_job(client, auth_headers)
        await upload_resume(client, auth_headers, run_pipeline)

        class Exploding:
            async def default_resume_version_id(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("the database went away")

        client._transport.app.dependency_overrides[get_matching_service] = Exploding  # type: ignore[attr-defined]

        response = await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": True, "applied": True},
        )

        assert response.status_code == 200, response.text
        saved = await row(db_session, job_id)
        assert saved.applied_at is not None
        assert saved.match_score_at_apply is None
