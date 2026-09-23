"""Answering a question, being marked, and the interview adapting (US-8.2, 8.3).

Separate from `test_interviews.py`, which covers starting and resuming. That is
one request and a read; this is a loop -- answer, mark, decide, ask -- and the
interesting assertions are about what the policy did with the mark.

Every test injects `FakeLLMProvider`, so the suite runs offline and twice the
same way.
"""

from __future__ import annotations

import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.fake import FakeLLMProvider
from app.models.enums import QuestionDifficulty
from app.services.interview.policy import GENERIC_TOPICS
from app.services.interview.session import ask_next_question, submit_answer
from tests.api.test_interviews import question_reply, read, start
from tests.api.test_job_match import upload_resume
from tests.api.test_jobs import API

DIMENSIONS = ("technical", "relevance", "completeness", "communication", "structure")


def score_reply(value: float = 0.9, **overrides: object) -> str:
    payload: dict[str, object] = {
        "scores": dict.fromkeys(DIMENSIONS, value),
        "feedback": "Clear, and it covered the rubric.",
        "strengths": ["concrete"],
        "improvements": ["say more about failure modes"],
        "cited_spans": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


async def asked(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    run_pipeline,
) -> tuple[str, str]:
    """An interview with its first question asked. Returns (interview, question)."""
    await upload_resume(client, headers, run_pipeline)
    created = await start(client, headers)
    interview_id = str(created["interview_id"])
    await ask_next_question(
        interview_id=uuid.UUID(interview_id),
        session=db_session,
        provider=FakeLLMProvider([question_reply(topic=GENERIC_TOPICS[0])]),
    )
    body = await read(client, headers, interview_id)
    return interview_id, body["questions"][0]["id"]


class TestRecordingAnAnswer:
    async def test_it_is_stored_before_anything_is_marked(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """What the candidate typed is theirs.

        The mark, the policy's decision and the next question are all model
        calls and go to the background. Losing the answer because a provider was
        slow would be the one unrecoverable failure here, so it is written
        synchronously before the 202.
        """
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )

        response = await client.post(
            f"{API}/interviews/{interview_id}/questions/{question_id}/answer",
            headers=auth_headers,
            json={"answer_text": "I would use dual writes and verify parity."},
        )

        assert response.status_code == 202, response.text
        answer = (await read(client, auth_headers, interview_id))["questions"][0]["answer"]
        assert answer["answer_text"].startswith("I would use dual writes")
        # Unmarked: the background task has not run here, and the schema says so
        # with a null rather than a zero.
        assert answer["score"] is None

    async def test_answering_twice_is_refused(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """409, with a UNIQUE constraint behind it.

        A second answer would give one question two scores and double its weight
        in the report. The request is well formed and the resource exists, so it
        is the state that refuses -- not a 404.
        """
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )
        url = f"{API}/interviews/{interview_id}/questions/{question_id}/answer"

        first = await client.post(url, headers=auth_headers, json={"answer_text": "One."})
        second = await client.post(url, headers=auth_headers, json={"answer_text": "Two."})

        assert first.status_code == 202
        assert second.status_code == 409

    async def test_a_question_that_is_not_in_this_interview_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        created = await start(client, auth_headers)

        response = await client.post(
            f"{API}/interviews/{created['interview_id']}/questions/{uuid.uuid4()}/answer",
            headers=auth_headers,
            json={"answer_text": "Anything."},
        )

        assert response.status_code == 404


class TestAdapting:
    """US-8.2: the interview reacts to how the answer scored."""

    async def test_a_strong_answer_takes_a_fresh_topic_and_records_the_decision(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """AC1 and AC2 together.

        `next_difficulty` is stored *with the score* rather than recomputed for
        the report. The policy can change, and a transcript read in a month
        should show the decision actually taken, not the one today's code would
        make.
        """
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )
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
                [score_reply(0.9), question_reply(topic=GENERIC_TOPICS[1])]
            ),
        )

        body = await read(client, auth_headers, interview_id)
        score = body["questions"][0]["answer"]["score"]
        assert float(score["overall_score"]) == 0.9
        # Breadth before depth: a fresh topic at the same rung while one is
        # uncovered, rather than drilling this one harder.
        assert score["next_difficulty"] == QuestionDifficulty.MEDIUM.value
        assert len(body["questions"]) == 2
        assert body["questions"][1]["topic"] == GENERIC_TOPICS[1]

    async def test_a_weak_answer_drops_a_rung_on_the_same_topic(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The other half of AC1.

        Moving on would leave the gap unexamined, which is the opposite of what
        somebody rehearsing wants.
        """
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )
        await client.post(
            f"{API}/interviews/{interview_id}/questions/{question_id}/answer",
            headers=auth_headers,
            json={"answer_text": "Not sure."},
        )

        await submit_answer(
            question_id=uuid.UUID(question_id),
            answer_text="Not sure.",
            session=db_session,
            provider=FakeLLMProvider(
                [
                    score_reply(0.2),
                    question_reply(
                        topic=GENERIC_TOPICS[0],
                        difficulty=QuestionDifficulty.EASY.value,
                    ),
                ]
            ),
        )

        body = await read(client, auth_headers, interview_id)
        assert body["questions"][0]["answer"]["score"]["next_difficulty"] == (
            QuestionDifficulty.EASY.value
        )
        assert body["questions"][1]["topic"] == GENERIC_TOPICS[0]
        assert body["questions"][1]["difficulty"] == QuestionDifficulty.EASY.value

    async def test_the_five_dimensions_all_reach_the_transcript(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """US-8.3 AC1 asks for five, so five are stored and five come back."""
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )
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
                [
                    score_reply(
                        0.6,
                        cited_spans=[
                            {"start": 0, "end": 11, "text": "Dual writes", "note": "the technique"}
                        ],
                    ),
                    question_reply(topic=GENERIC_TOPICS[1]),
                ]
            ),
        )

        score = (await read(client, auth_headers, interview_id))["questions"][0]["answer"]["score"]
        for name in DIMENSIONS:
            assert float(score[f"{name}_score"]) == 0.6, name
        assert score["feedback"]

        # US-8.3 AC2: the citation points at the candidate's own words, and the
        # offsets were verified against the answer before this was stored.
        spans = score["cited_spans"]
        assert len(spans) == 1
        assert spans[0]["text"] == answer[spans[0]["start"] : spans[0]["end"]]

    async def test_an_unmarkable_answer_says_so_and_keeps_the_answer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """No mark is reported, never invented.

        There is no sensible default for "how good was this", and 0.5 would be a
        fabrication with a confident face -- it would also feed the policy and
        pick the next question.
        """
        interview_id, question_id = await asked(
            client, db_session, auth_headers, run_pipeline
        )
        answer = "Something I said."
        await client.post(
            f"{API}/interviews/{interview_id}/questions/{question_id}/answer",
            headers=auth_headers,
            json={"answer_text": answer},
        )

        await submit_answer(
            question_id=uuid.UUID(question_id),
            answer_text=answer,
            session=db_session,
            provider=FakeLLMProvider(["not json", "still not json"]),
        )

        body = await read(client, auth_headers, interview_id)
        stored = body["questions"][0]["answer"]
        assert stored["answer_text"] == answer
        assert stored["score"] is None
        assert body["summary_feedback"]
        # And no next question: the policy was never given a score to act on.
        assert len(body["questions"]) == 1
