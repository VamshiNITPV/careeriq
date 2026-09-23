"""Finding your way back to an interview you left (US-8.1 AC2).

The state has always survived in Postgres. What was missing was a route back to
it: without a list, "resumable" was only true for somebody who kept the URL.

Separate from `test_interviews.py` because these are aggregate queries -- counts
and an average computed in SQL -- and the interesting assertions are about what
the aggregate says when there is nothing to aggregate.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.fake import FakeLLMProvider
from app.services.interview.policy import GENERIC_TOPICS
from app.services.interview.session import ask_next_question, submit_answer
from tests.api.test_interview_answers import score_reply
from tests.api.test_interviews import question_reply, read, start
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API


async def listed(client: AsyncClient, headers: dict[str, str], **params: object) -> dict:
    response = await client.get(f"{API}/interviews", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestListing:
    async def test_an_interview_just_started_appears(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        created = await start(client, auth_headers)

        body = await listed(client, auth_headers)

        assert body["total"] == 1
        row = body["items"][0]
        assert row["id"] == str(created["interview_id"])
        assert row["target_role"] == "Backend Engineer"

    async def test_nothing_started_is_an_empty_list_not_an_error(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        body = await listed(client, auth_headers)

        assert body == {"items": [], "total": 0}

    async def test_newest_first(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        first = await start(client, auth_headers, target_role="Older Role")
        second = await start(client, auth_headers, target_role="Newer Role")

        body = await listed(client, auth_headers)

        assert [row["id"] for row in body["items"]] == [
            str(second["interview_id"]),
            str(first["interview_id"]),
        ]

    async def test_another_users_interviews_are_not_listed(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Scoped in the WHERE clause, like the read route.

        A transcript says what somebody is rehearsing for and how they are
        doing at it, which is a more revealing thing to leak than most rows in
        this system -- and a list leaks all of them at once.
        """
        await start(client, auth_headers)

        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "other-lister@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        intruder = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        assert await listed(client, intruder) == {"items": [], "total": 0}


class TestTheCounts:
    async def test_answered_is_not_the_same_as_asked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The distinction the list exists to show.

        The last question is asked and unanswered for as long as somebody is
        sitting there thinking about it. Reporting one number for both would
        say an interview is further along than it is.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )

        row = (await listed(client, auth_headers))["items"][0]

        assert row["questions_asked"] == 1
        assert row["answered"] == 0

    async def test_an_unmarked_interview_has_no_average_rather_than_zero(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """0.0 would read as having done badly, which is a claim about them.

        The same rule the scorer follows: there is no sensible default for "how
        good was this", so the absence is reported as an absence.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        await ask_next_question(
            interview_id=uuid.UUID(str(created["interview_id"])),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )

        row = (await listed(client, auth_headers))["items"][0]

        assert row["average_score"] is None

    async def test_the_average_is_over_the_marks_that_exist(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )
        question_id = (await read(client, auth_headers, interview_id))["questions"][0]["id"]
        answer = "Dual writes, then verify row counts match."
        await client.post(
            f"{API}/interviews/{interview_id}/questions/{question_id}/answer",
            headers=auth_headers,
            json={"answer_text": answer},
        )
        await submit_answer(
            question_id=uuid.UUID(question_id),
            answer_text=answer,
            session=db_session,
            provider=FakeLLMProvider(
                [score_reply(0.8), question_reply(topic=GENERIC_TOPICS[1])]
            ),
        )

        row = (await listed(client, auth_headers))["items"][0]

        assert row["answered"] == 1
        # Quantized to the three places the column stores. `avg` over NUMERIC
        # widens the scale, and 0.8000000000000000 is noise dressed as
        # precision.
        assert float(row["average_score"]) == 0.8
        assert str(row["average_score"]) == "0.800"

    async def test_one_interviews_answers_do_not_count_towards_another(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The correlated subquery, checked.

        An uncorrelated one would count every answer in the table and give both
        rows the same figure -- which looks entirely plausible on a list.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        answered = await start(client, auth_headers, target_role="Answered Role")
        interview_id = str(answered["interview_id"])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )
        question_id = (await read(client, auth_headers, interview_id))["questions"][0]["id"]
        await client.post(
            f"{API}/interviews/{interview_id}/questions/{question_id}/answer",
            headers=auth_headers,
            json={"answer_text": "Something."},
        )
        await start(client, auth_headers, target_role="Untouched Role")

        rows = {r["target_role"]: r for r in (await listed(client, auth_headers))["items"]}

        assert rows["Answered Role"]["answered"] == 1
        assert rows["Untouched Role"]["answered"] == 0


class TestPaging:
    async def test_limit_and_offset_walk_the_list_without_repeating(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        for index in range(3):
            await start(client, auth_headers, target_role=f"Role {index}")

        first = await listed(client, auth_headers, limit=2, offset=0)
        second = await listed(client, auth_headers, limit=2, offset=2)

        assert len(first["items"]) == 2
        assert len(second["items"]) == 1
        assert first["total"] == second["total"] == 3
        # The tiebreak on id earns its place here: without it two rows created
        # in the same millisecond are free to swap between the two pages, and
        # one of them is never shown at all.
        ids = [row["id"] for row in first["items"] + second["items"]]
        assert len(set(ids)) == 3

    async def test_total_counts_everything_not_just_this_page(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        for index in range(3):
            await start(client, auth_headers, target_role=f"Role {index}")

        body = await listed(client, auth_headers, limit=1)

        assert len(body["items"]) == 1
        assert body["total"] == 3
