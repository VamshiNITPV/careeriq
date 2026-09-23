"""Starting and resuming a mock interview (US-8.1).

Every test injects `FakeLLMProvider`. `conftest` pins `LLM_PROVIDER=none` so a
forgotten injection fails loudly rather than quietly calling Google -- a guard
that exists because a unit test here once made a real API call and got a 503
back from it.
"""

from __future__ import annotations

import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.fake import FakeLLMProvider
from app.models.enums import InterviewStatus, QuestionDifficulty
from app.services.interview.session import ask_next_question
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API

ROLE = "Backend Engineer"


def question_reply(
    *,
    topic: str,
    difficulty: str = QuestionDifficulty.MEDIUM.value,
    grounded_in: str | None = None,
) -> str:
    return json.dumps(
        {
            "question_text": "Describe how you would approach that.",
            "topic": topic,
            "difficulty": difficulty,
            "expected_points": ["names a concrete trade-off", "explains why"],
            "grounded_in": grounded_in,
        }
    )


async def start(
    client: AsyncClient, headers: dict[str, str], **body: object
) -> dict[str, object]:
    response = await client.post(
        f"{API}/interviews", headers=headers, json={"target_role": ROLE, **body}
    )
    assert response.status_code == 202, response.text
    return response.json()


async def read(client: AsyncClient, headers: dict[str, str], interview_id: str) -> dict:
    response = await client.get(f"{API}/interviews/{interview_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestStarting:
    async def test_it_answers_before_the_question_exists(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """202 with somewhere to poll.

        A model call takes seconds. Holding the request open for it makes every
        client's timeout our problem, which is the reasoning
        `POST /optimize/analyze` already records.
        """
        created = await start(client, auth_headers)

        assert created["status"] == InterviewStatus.CREATED.value
        assert created["poll_url"].endswith(str(created["interview_id"]))

    async def test_an_unknown_job_fails_now_rather_than_in_the_background(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Checked in the request, where a bad id can still be reported.

        Queued and checked later, it would fail where nobody is looking and the
        user would poll a session that never produces anything.
        """
        response = await client.post(
            f"{API}/interviews",
            headers=auth_headers,
            json={"target_role": ROLE, "target_job_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    async def test_a_budget_outside_the_bounds_is_refused(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Zero ends an interview before it starts; the upper bound keeps one
        # session from spending a free tier's whole day.
        for budget in (0, 2, 21, 500):
            response = await client.post(
                f"{API}/interviews",
                headers=auth_headers,
                json={"target_role": ROLE, "question_budget": budget},
            )
            assert response.status_code == 422, budget


class TestTheFirstQuestion:
    async def test_a_generated_question_is_stored_and_advances_the_state(
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

        # The blueprint falls back to the generic list here -- the test corpus
        # has no Backend Engineer postings -- so the first topic is known.
        from app.services.interview.policy import GENERIC_TOPICS

        provider = FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])])
        await ask_next_question(
            interview_id=uuid.UUID(interview_id), session=db_session, provider=provider
        )

        body = await read(client, auth_headers, interview_id)
        assert len(body["questions"]) == 1
        question = body["questions"][0]
        assert question["question_order"] == 1
        assert question["topic"] == GENERIC_TOPICS[0]
        # The rubric travels with the question. A candidate rehearsing alone
        # deserves to know what a strong answer contains, and it was written
        # before any answer existed so showing it cannot change the mark.
        assert question["expected_points"]

        assert body["status"] == InterviewStatus.IN_PROGRESS.value
        assert body["questions_asked"] == 1
        assert body["topics_covered"] == [GENERIC_TOPICS[0]]

    async def test_the_grounding_is_kept_not_just_checked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The gate verified this and then threw it away, until 0022.

        Nothing caught it: every test passed either way, because none asserted
        on a column that did not exist. It showed up only on reading the row the
        real model wrote. A grounding nobody can inspect afterwards is a
        grounding nobody can audit, and `questions.py` promises a report can say
        when personalisation did not hold -- a promise kept in a log file is not
        kept.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)

        from app.services.interview.policy import GENERIC_TOPICS

        # Verbatim from the sample resume. The anchor check accepts nothing
        # else, which is the whole point -- a first draft of this test used a
        # phrase that only sounded resume-ish and was correctly rejected.
        grounding = "Built and maintained REST APIs in Python"
        await ask_next_question(
            interview_id=uuid.UUID(str(created["interview_id"])),
            session=db_session,
            provider=FakeLLMProvider(
                [question_reply(topic=GENERIC_TOPICS[0], grounded_in=grounding)]
            ),
        )

        body = await read(client, auth_headers, str(created["interview_id"]))
        question = body["questions"][0]
        assert question["grounded_in"] == grounding
        assert question["degraded"] is False

    async def test_the_resume_goes_in_the_context_block_not_the_instruction(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """ADR-014. A resume is attacker-supplied text in principle.

        Somebody can upload one saying "ignore your instructions". Putting it in
        the instruction would defeat the delimiting entirely, and this is the
        only assertion that catches it -- the answer looks identical either way.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)

        from app.services.interview.policy import GENERIC_TOPICS

        provider = FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])])
        await ask_next_question(
            interview_id=uuid.UUID(str(created["interview_id"])),
            session=db_session,
            provider=provider,
        )

        prompt = provider.calls[0]
        assert any("resume" in label.lower() for label in prompt.context)
        assert "Asha" not in prompt.instruction

    async def test_no_resume_says_so_rather_than_hanging(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A client polling forever is the failure worth designing against.

        The generation runs after the response has gone, so there is no request
        left to fail -- the reason has to reach the row or it reaches nobody.
        """
        created = await start(client, auth_headers)

        await ask_next_question(
            interview_id=uuid.UUID(str(created["interview_id"])),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic="anything")]),
        )

        body = await read(client, auth_headers, str(created["interview_id"]))
        assert body["questions"] == []
        assert "resume" in (body["summary_feedback"] or "").lower()
        # Still CREATED, not ABANDONED: the user has not walked away, and a
        # retry after uploading a resume should work.
        assert body["status"] == InterviewStatus.CREATED.value

    async def test_a_model_that_never_returns_a_usable_question_is_reported(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)

        # Three replies: two personalised attempts and the ungrounded fallback.
        provider = FakeLLMProvider(["not json", "still not json", "nor this"])
        await ask_next_question(
            interview_id=uuid.UUID(str(created["interview_id"])),
            session=db_session,
            provider=provider,
        )

        body = await read(client, auth_headers, str(created["interview_id"]))
        assert body["questions"] == []
        assert body["summary_feedback"]
        # The budget is untouched. A failed generation that had already
        # incremented the counter would spend a question without asking one.
        assert body["questions_asked"] == 0


class TestResuming:
    async def test_the_transcript_survives_a_new_request(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """US-8.1 AC2.

        The state machine lives in Postgres rather than in a model's context
        window, which is ADR-013's decision and what makes this answerable at
        all: the same GET tomorrow returns the same interview.
        """
        await upload_resume(client, auth_headers, run_pipeline)
        created = await start(client, auth_headers)
        interview_id = str(created["interview_id"])

        from app.services.interview.policy import GENERIC_TOPICS

        await ask_next_question(
            interview_id=uuid.UUID(interview_id),
            session=db_session,
            provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
        )

        first = await read(client, auth_headers, interview_id)
        second = await read(client, auth_headers, interview_id)

        assert first == second
        assert first["questions"][0]["question_text"]

    async def test_another_users_interview_is_404_not_403(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """403 would confirm it exists.

        An interview transcript says what somebody is rehearsing for and how
        they are doing at it, which is a more revealing thing to confirm than
        most rows in this schema.
        """
        created = await start(client, auth_headers)

        registered = await client.post(
            f"{API}/auth/register",
            json={"email": "other-candidate@example.com", "password": "correct-horse-9"},
        )
        assert registered.status_code == 201, registered.text
        intruder = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

        response = await client.get(
            f"{API}/interviews/{created['interview_id']}", headers=intruder
        )

        assert response.status_code == 404

    async def test_an_unknown_interview_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/interviews/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404
