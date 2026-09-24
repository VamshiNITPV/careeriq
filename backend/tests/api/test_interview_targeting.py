"""Starting an interview against a specific job (US-8.1 AC1).

Three ways lead here and two of them carry a `target_job_id`: a posting the user
just pasted, and a job they applied to. Both send the same body, so there is one
path server-side and these tests cover it once.

`test_another_users_application_is_not_linked` is the security test. Everything
else here is about what gets recorded.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview
from tests.api.test_interviews import start
from tests.api.test_jobs import API, BACKEND_BODY


async def _job_id(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    company: str | None = None,
    title: str = "Backend Engineer",
) -> str:
    """A job in the corpus, through the real paste endpoint.

    The same route the interview's paste path will use, so these tests exercise
    a posting that was genuinely parsed -- sections detected, skills split
    REQUIRED from PREFERRED -- rather than one hand-built to suit them.
    """
    body: dict[str, object] = {
        "description": BACKEND_BODY,
        "title": title,
        "source_url": f"https://jobs.example.com/{uuid.uuid4().hex}",
    }
    if company is not None:
        body["company"] = company
    response = await client.post(f"{API}/jobs", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["job"]["id"])


async def _stored(session: AsyncSession, interview_id: str) -> Interview:
    interview = await session.scalar(
        select(Interview).where(Interview.id == uuid.UUID(interview_id))
    )
    assert interview is not None
    return interview


class TestTargetingAJob:
    async def test_the_job_is_recorded_on_the_interview(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        job_id = await _job_id(client, auth_headers)

        created = await start(client, auth_headers, target_job_id=job_id)

        interview = await _stored(db_session, str(created["interview_id"]))
        assert str(interview.target_job_id) == job_id

    async def test_a_job_that_does_not_exist_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/interviews",
            headers=auth_headers,
            json={"target_role": "Backend Engineer", "target_job_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    async def test_a_job_nobody_applied_to_still_starts(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The outer-join case, and it is the common one.

        Every interview started from a freshly pasted posting lands here: the job
        exists, no application references it, and that must not be an error. An
        inner join would have refused all of them.
        """
        job_id = await _job_id(client, auth_headers)

        created = await start(client, auth_headers, target_job_id=job_id)

        interview = await _stored(db_session, str(created["interview_id"]))
        assert interview.application_id is None
        assert str(interview.target_job_id) == job_id

    async def test_no_relationship_to_the_job_is_required(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Somebody else's submission is still a job you can rehearse against.

        Jobs are a shared corpus and `GET /jobs/{id}` is open to any
        authenticated caller, so requiring a relationship would break
        "interview against a job I found in browse" and protect nothing.
        """
        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "job-owner@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        owner = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
        job_id = await _job_id(client, owner)

        created = await start(client, auth_headers, target_job_id=job_id)

        assert created["interview_id"]


class TestLinkingTheApplication:
    """`interviews.application_id` has existed unused since 0021. This fills it."""

    async def test_it_is_linked_when_the_caller_has_applied(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        job_id = await _job_id(client, auth_headers)
        applied = await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": False, "applied": True},
        )
        assert applied.status_code in (200, 201), applied.text

        created = await start(client, auth_headers, target_job_id=job_id)

        interview = await _stored(db_session, str(created["interview_id"]))
        # Read off the row rather than the response: nothing exposes this, and
        # nothing should -- its value is in joins and funnel analytics, not on a
        # screen.
        assert interview.application_id is not None

    async def test_another_users_application_is_not_linked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The security test.

        Without `Application.user_id == user.id` in the ON clause, a caller
        starting an interview against a job somebody else applied to would have
        that stranger's application row linked to their interview -- a cross-user
        foreign key, and a membership oracle over the applications table.

        And it must stay a 202: the job is real, the interview is legitimate,
        and the only thing absent is a link that was never theirs.
        """
        job_id = await _job_id(client, auth_headers)
        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "other-applicant@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        stranger = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
        applied = await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=stranger,
            json={"saved": False, "applied": True},
        )
        assert applied.status_code in (200, 201), applied.text

        created = await start(client, auth_headers, target_job_id=job_id)

        interview = await _stored(db_session, str(created["interview_id"]))
        assert interview.application_id is None

    async def test_a_saved_but_unapplied_job_still_links(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """`is_saved` and `status` are independent facts on one row.

        The link records "this interview was practice for that tracked job", and
        a bookmark is a tracked job. Which statuses the *picker* offers is a
        separate decision made in the client.
        """
        job_id = await _job_id(client, auth_headers)
        await client.put(
            f"{API}/jobs/{job_id}/application",
            headers=auth_headers,
            json={"saved": True, "applied": False},
        )

        created = await start(client, auth_headers, target_job_id=job_id)

        interview = await _stored(db_session, str(created["interview_id"]))
        assert interview.application_id is not None

    async def test_a_role_only_interview_links_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        created = await start(client, auth_headers)

        interview = await _stored(db_session, str(created["interview_id"]))
        assert interview.target_job_id is None
        assert interview.application_id is None


class TestTheListSaysWhatItWasFor:
    async def test_a_targeted_interview_carries_the_job_and_company(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job_id = await _job_id(client, auth_headers, company="Acme Payments")
        created = await start(client, auth_headers, target_job_id=job_id)

        response = await client.get(f"{API}/interviews", headers=auth_headers)
        assert response.status_code == 200, response.text
        row = next(
            r for r in response.json()["items"] if r["id"] == str(created["interview_id"])
        )

        assert row["target_job_id"] == job_id
        assert row["target_company"] == "Acme Payments"

    async def test_a_role_only_interview_carries_neither(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The outer joins, checked from the other side: a role-only interview
        # must still appear, with nulls rather than being dropped by the join.
        await start(client, auth_headers)

        response = await client.get(f"{API}/interviews", headers=auth_headers)
        row = response.json()["items"][0]

        assert row["target_job_id"] is None
        assert row["target_company"] is None
