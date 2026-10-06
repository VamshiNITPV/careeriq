"""Asking again after a failure that was nobody's fault (US-8.1).

`_fail` has claimed since 9.1 that "the status stays CREATED, so a retry is
still possible". Nothing offered one for four phases, so a transient 503 from
the provider killed an interview permanently -- and mid-interview it stranded the
whole transcript, answers and marks included.

The guard is the interesting half. Generation *appends*, so retrying while a
question is already waiting would ask a second one and leave the candidate two
questions deep in a sequence the policy believes is one.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.fake import FakeLLMProvider
from app.models.enums import InterviewStatus
from app.models.interview import Interview
from app.services.interview.policy import GENERIC_TOPICS
from app.services.interview.session import ask_next_question, submit_answer
from tests.api.test_interviews import question_reply, read, start
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API


async def _retry(client: AsyncClient, headers: dict[str, str], interview_id: str):
    return await client.post(f"{API}/interviews/{interview_id}/retry", headers=headers)


async def _row(session: AsyncSession, interview_id: str) -> Interview:
    interview = await session.scalar(
        select(Interview).where(Interview.id == uuid.UUID(interview_id))
    )
    assert interview is not None
    return interview


class TestRetrying:
    async def test_a_failed_interview_can_try_again(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The whole point: a provider outage is not a dead interview.

        The common case really is transient -- Gemini overloaded for a minute,
        fine afterwards -- and before this the only way forward was starting
        over.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        # Fail it the way the provider does.
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider(error=RuntimeError("provider down")),
        )
        assert (await _row(db_session, interview_id)).summary_feedback is not None

        response = await _retry(client, auth_headers, interview_id)

        assert response.status_code == 202, response.text
        # Cleared before the task runs, not after it succeeds: the client polls
        # this row, and the old reason beside a spinner would read as a second
        # failure.
        assert (await _row(db_session, interview_id)).summary_feedback is None

    async def test_the_second_attempt_produces_the_question(
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
            provider=FakeLLMProvider(error=RuntimeError("provider down")),
        )

        await _retry(client, auth_headers, interview_id)
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )

        body = await read(client, auth_headers, interview_id)
        assert len(body["questions"]) == 1
        assert body["summary_feedback"] is None

    async def test_it_is_refused_while_a_question_is_waiting(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The guard that matters.

        Generation appends. Retrying here asks a second question and leaves the
        candidate two deep in a sequence the policy believes is one -- and the
        unique index on (interview_id, question_order) would surface that as an
        unexplained 500 rather than as an answer.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )

        response = await _retry(client, auth_headers, interview_id)

        assert response.status_code == 409, response.text
        assert len((await read(client, auth_headers, interview_id))["questions"]) == 1

    async def test_an_unmarked_answer_is_scored_rather_than_skipped(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
        background_calls: list[tuple],
    ) -> None:
        """Found in the running app, and the first version of this route got it
        wrong.

        Scoring and generation fail separately. When an answer exists and was
        never marked, it is *scoring* that failed -- and asking the next question
        instead leaves that answer unmarked forever, with the policy entering at
        the neutral band rather than reacting to how they actually did. Worse, it
        is unrecoverable: nothing looks stuck afterwards, so no further retry is
        ever offered.
        """
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
        # Scoring fails the way the provider does.
        await submit_answer(
            question_id=uuid.UUID(question_id),
            answer_text=answer,
            session=db_session,
            provider=FakeLLMProvider(error=RuntimeError("provider down")),
        )
        body = await read(client, auth_headers, interview_id)
        assert body["questions"][0]["answer"]["score"] is None

        background_calls.clear()

        response = await _retry(client, auth_headers, interview_id)

        assert response.status_code == 202, response.text
        # Asserted on *what was queued*, not on its effect. The runners are
        # recorded rather than run in tests, so both choices leave the database
        # identical -- which is exactly how the first version of this test passed
        # a mutation that always generated.
        assert background_calls == [("submit_answer", uuid.UUID(question_id), answer)]

    async def test_a_clean_interview_retries_the_question_instead(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
        background_calls: list[tuple],
    ) -> None:
        # The other branch: nothing unmarked, so generation is what failed.
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider(error=RuntimeError("provider down")),
        )
        background_calls.clear()

        await _retry(client, auth_headers, interview_id)

        assert background_calls == [("ask_next_question", uuid.UUID(interview_id))]

    async def test_a_finished_interview_is_refused(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])
        interview = await _row(db_session, interview_id)
        interview.status = InterviewStatus.COMPLETED
        await db_session.commit()

        response = await _retry(client, auth_headers, interview_id)

        assert response.status_code == 409, response.text

    async def test_another_users_interview_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Scoped through `_owned`, like every other route here: 403 would confirm
        # the interview exists, and a transcript is a revealing thing to confirm.
        created = await start(client, auth_headers)
        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "other-retrier@example.com", "password": "correct-horse-9"},
        )
        intruder = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        response = await _retry(client, intruder, str(created["interview_id"]))

        assert response.status_code == 404

    async def test_an_unknown_interview_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await _retry(client, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
