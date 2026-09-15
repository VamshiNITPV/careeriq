"""The /optimize endpoints (US-6.1, api.md section 2.7).

Three properties carry the weight here, and each has a test that fails if the
property breaks:

* A suggestion is applied because the user named its id. Nothing infers it.
* The source resume version is never modified. Accepting creates a new one.
* Another user's analysis is 404, not 403 -- a 403 confirms the id exists.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.models.enums import AnalysisStatus, JobSource, JobStatus, SuggestionDecision
from app.models.job import Job
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.models.resume import Resume, ResumeVersion

API = "/api/v1"

RESUME_TEXT = """Priya Raman
Senior Backend Engineer

Experience
- Worked on the payments backend.
- Reduced p99 latency by 35%.

Skills
Python, Django, PostgreSQL
"""


async def a_version(session: AsyncSession, user_id: uuid.UUID) -> ResumeVersion:
    resume = Resume(id=uuid7(), user_id=user_id, title="CV")
    session.add(resume)
    await session.flush()
    version = ResumeVersion(
        id=uuid7(),
        resume_id=resume.id,
        version_number=1,
        storage_key=f"test/{uuid7()}",
        original_filename="priya.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        content_hash=hashlib.sha256(RESUME_TEXT.encode()).hexdigest(),
        raw_text=RESUME_TEXT,
    )
    session.add(version)
    await session.flush()
    return version


async def a_job(session: AsyncSession) -> Job:
    job = Job(
        id=uuid7(),
        title="Senior Backend Engineer",
        description_raw="Backend engineer for payment systems. Python and Django.",
        content_hash=hashlib.sha256(f"{uuid7()}".encode()).hexdigest(),
        source=JobSource.USER_SUBMITTED,
        status=JobStatus.ACTIVE,
    )
    session.add(job)
    await session.flush()
    return job


async def a_completed_analysis(
    session: AsyncSession, user_id: uuid.UUID, *, suggestions: int = 1
) -> tuple[OptimizationAnalysis, list[OptimizationSuggestion]]:
    """An analysis as the service would leave it, without calling a model."""
    version = await a_version(session, user_id)
    job = await a_job(session)
    analysis = OptimizationAnalysis(
        id=uuid7(),
        user_id=user_id,
        resume_version_id=version.id,
        job_id=job.id,
        status=AnalysisStatus.COMPLETE,
    )
    session.add(analysis)
    await session.flush()

    rows = []
    originals = ["Worked on the payments backend.", "Reduced p99 latency by 35%."]
    rewrites = [
        "Built and maintained payment processing services.",
        "Cut p99 latency by 35%.",
    ]
    for index in range(suggestions):
        row = OptimizationSuggestion(
            id=uuid7(),
            analysis_id=analysis.id,
            position=index + 1,
            section="experience",
            original=originals[index],
            suggested=rewrites[index],
            rationale="The job is about payments.",
            grounded_in=[originals[index]],
            validation={"passed": True, "fabricated_entities": []},
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return analysis, rows


async def user_uuid(registered_user: dict) -> uuid.UUID:
    return uuid.UUID(str(registered_user["user"]["id"]))  # type: ignore[index]


class TestStartingAnAnalysis:
    async def test_it_answers_202_without_waiting_for_the_model(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        """A model call takes seconds. Holding the request open for it makes
        every client's timeout our problem."""
        version = await a_version(db_session, await user_uuid(registered_user))
        job = await a_job(db_session)

        response = await client.post(
            f"{API}/optimize/analyze",
            headers=auth_headers,
            json={"resume_version_id": str(version.id), "job_id": str(job.id)},
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["poll_url"].endswith(body["analysis_id"])

    async def test_an_unknown_resume_version_is_404_before_anything_is_queued(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        """Checked here rather than in the background, so a bad request fails
        with a precise status instead of failing where nobody is looking."""
        job = await a_job(db_session)

        response = await client.post(
            f"{API}/optimize/analyze",
            headers=auth_headers,
            json={"resume_version_id": str(uuid.uuid4()), "job_id": str(job.id)},
        )

        assert response.status_code == 404

    async def test_someone_elses_resume_version_is_404(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        """Not 403. A 403 confirms the id exists (US-1.5 AC1)."""
        stranger = uuid7()
        from app.models.user import User

        db_session.add(User(id=stranger, email=f"s-{stranger}@example.com", password_hash="x" * 60))
        await db_session.flush()
        version = await a_version(db_session, stranger)
        job = await a_job(db_session)

        response = await client.post(
            f"{API}/optimize/analyze",
            headers=auth_headers,
            json={"resume_version_id": str(version.id), "job_id": str(job.id)},
        )

        assert response.status_code == 404

    async def test_it_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/optimize/analyze",
            json={"resume_version_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4())},
        )
        assert response.status_code == 401


class TestReadingAnAnalysis:
    async def test_it_returns_the_suggestions_in_order(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        analysis, _ = await a_completed_analysis(
            db_session, await user_uuid(registered_user), suggestions=2
        )

        body = (await client.get(f"{API}/optimize/{analysis.id}", headers=auth_headers)).json()

        assert [s["position"] for s in body["suggestions"]] == [1, 2]
        assert body["status"] == "COMPLETE"

    async def test_it_reports_how_many_the_validator_rejected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        """Otherwise an empty list is ambiguous: a validator that rejected
        everything looks exactly like a model with nothing to say."""
        analysis, _ = await a_completed_analysis(db_session, await user_uuid(registered_user))
        analysis.rejected_by_validator = 3
        await db_session.flush()

        body = (await client.get(f"{API}/optimize/{analysis.id}", headers=auth_headers)).json()

        assert body["rejected_by_validator"] == 3

    async def test_another_users_analysis_is_404(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
    ) -> None:
        stranger = uuid7()
        from app.models.user import User

        db_session.add(User(id=stranger, email=f"o-{stranger}@example.com", password_hash="x" * 60))
        await db_session.flush()
        analysis, _ = await a_completed_analysis(db_session, stranger)

        response = await client.get(f"{API}/optimize/{analysis.id}", headers=auth_headers)

        assert response.status_code == 404


class TestApplying:
    async def test_the_source_version_is_never_modified(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        """US-6.1 AC3, and the reason "undo" means restoring a version rather
        than hoping an edit was reversible."""
        analysis, rows = await a_completed_analysis(db_session, await user_uuid(registered_user))
        await db_session.commit()
        before = (await db_session.get(ResumeVersion, analysis.resume_version_id)).raw_text  # type: ignore[union-attr]

        response = await client.post(
            f"{API}/optimize/{analysis.id}/apply",
            headers=auth_headers,
            json={"accepted_suggestion_ids": [str(rows[0].id)]},
        )

        assert response.status_code == 201, response.text
        source = await db_session.get(ResumeVersion, analysis.resume_version_id)
        await db_session.refresh(source)  # type: ignore[arg-type]
        assert source.raw_text == before  # type: ignore[union-attr]

    async def test_it_creates_a_new_version_carrying_the_rewrite(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        analysis, rows = await a_completed_analysis(db_session, await user_uuid(registered_user))
        await db_session.commit()

        body = (
            await client.post(
                f"{API}/optimize/{analysis.id}/apply",
                headers=auth_headers,
                json={"accepted_suggestion_ids": [str(rows[0].id)]},
            )
        ).json()

        created = await db_session.get(ResumeVersion, uuid.UUID(body["resume_version_id"]))
        assert body["version_number"] == 2
        assert rows[0].suggested in created.raw_text  # type: ignore[union-attr,operator]
        assert rows[0].original not in created.raw_text  # type: ignore[union-attr,operator]

    async def test_an_unnamed_suggestion_is_rejected_not_applied(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        """Nothing is inferred. A suggestion is applied because the user named
        its id, and everything else in the analysis is decided as rejected so it
        is never re-offered."""
        analysis, rows = await a_completed_analysis(
            db_session, await user_uuid(registered_user), suggestions=2
        )
        await db_session.commit()

        await client.post(
            f"{API}/optimize/{analysis.id}/apply",
            headers=auth_headers,
            json={"accepted_suggestion_ids": [str(rows[0].id)]},
        )

        stored = list(
            await db_session.scalars(
                select(OptimizationSuggestion)
                .where(OptimizationSuggestion.analysis_id == analysis.id)
                .order_by(OptimizationSuggestion.position)
            )
        )
        for row in stored:
            await db_session.refresh(row)
        assert stored[0].decision is SuggestionDecision.ACCEPTED
        assert stored[1].decision is SuggestionDecision.REJECTED
        assert stored[1].applied_version_id is None

    # "A failed apply leaves every decision untouched" is asserted in
    # tests/unit/test_apply_suggestions.py rather than here. Through HTTP it
    # cannot be observed: the session dependency rolls back on any exception --
    # correct in production, where each request owns its session -- and in this
    # harness that discards the rows the test itself created. The invariant is
    # real, so it is tested where it can actually be seen.

    async def test_accepting_nothing_creates_no_version(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        """A version identical to its parent is clutter with a number on it, and
        implies a change the user cannot find."""
        analysis, _ = await a_completed_analysis(db_session, await user_uuid(registered_user))
        await db_session.commit()

        response = await client.post(
            f"{API}/optimize/{analysis.id}/apply",
            headers=auth_headers,
            json={"accepted_suggestion_ids": []},
        )

        assert response.status_code == 422
        versions = await db_session.scalars(
            select(ResumeVersion).where(ResumeVersion.resume_id.is_not(None))
        )
        assert len([v for v in versions if v.mime_type == "text/plain"]) == 0

    async def test_an_unfinished_analysis_cannot_be_applied(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
    ) -> None:
        analysis, rows = await a_completed_analysis(db_session, await user_uuid(registered_user))
        analysis.status = AnalysisStatus.RUNNING
        await db_session.commit()

        response = await client.post(
            f"{API}/optimize/{analysis.id}/apply",
            headers=auth_headers,
            json={"accepted_suggestion_ids": [str(rows[0].id)]},
        )

        assert response.status_code in (409, 422)

    @pytest.mark.parametrize("payload", [{"unexpected": 1}, {"accepted_suggestion_ids": "nope"}])
    async def test_a_malformed_body_is_refused(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict,
        payload: dict,
    ) -> None:
        analysis, _ = await a_completed_analysis(db_session, await user_uuid(registered_user))
        await db_session.commit()

        response = await client.post(
            f"{API}/optimize/{analysis.id}/apply", headers=auth_headers, json=payload
        )

        assert response.status_code == 422
