"""Starting and resuming a mock interview (US-8.1).

Two routes. Creating one answers immediately and generates the first question
behind the response; reading one returns the whole transcript so far.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CurrentUser,
    DbSession,
    InterviewAnswerRunnerDep,
    InterviewRunnerDep,
)
from app.core.exceptions import InvalidStateTransitionError, ResourceNotFoundError
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.models.interview import Interview, InterviewAnswer, InterviewQuestion
from app.models.job import Job
from app.schemas.common import ErrorResponse
from app.schemas.interview import (
    AnswerSubmit,
    InterviewCreate,
    InterviewCreated,
    InterviewRead,
)

log = get_logger(__name__)

router = APIRouter(prefix="/interviews", tags=["interviews"])


async def _owned(session: DbSession, interview_id: uuid.UUID, user_id: uuid.UUID) -> Interview:
    """One interview the caller owns, with its questions loaded.

    Scoped on `user_id` in the WHERE clause rather than fetched and then
    checked, so "not yours" and "not there" are indistinguishable by
    construction. A 403 would confirm the row exists, and an interview
    transcript is a more revealing thing to confirm than most -- it says what
    somebody is rehearsing for and how they are doing at it.
    """
    interview = await session.scalar(
        select(Interview)
        # The whole chain, eagerly. `InterviewRead` serialises questions, their
        # answers and their scores, and a lazy load inside async has no await
        # point -- that is MissingGreenlet at render time rather than at the
        # attribute access, which is the same trap `models/application.py`
        # records for its own `job` relationship.
        .options(
            selectinload(Interview.questions)
            .selectinload(InterviewQuestion.answer)
            .selectinload(InterviewAnswer.score)
        )
        .where(Interview.id == interview_id, Interview.user_id == user_id)
        # Refresh what is already in the identity map rather than returning it
        # as last loaded. Without this, an `Interview` whose `questions` were
        # loaded earlier in the same session comes back with that collection
        # unchanged -- so a question written since is simply absent from the
        # response, with no error anywhere. `expire_on_commit=False` is what
        # makes that possible, and it is set deliberately elsewhere.
        .execution_options(populate_existing=True)
    )
    if interview is None:
        raise ResourceNotFoundError("Interview")
    return interview


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InterviewCreated,
    summary="Start a mock interview",
    responses={404: {"model": ErrorResponse, "description": "Job not found"}},
)
async def create_interview(
    payload: InterviewCreate,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
    ask_next: InterviewRunnerDep,
) -> InterviewCreated:
    """Create a session and start generating its first question.

    **202, not 201.** A model call takes seconds, and holding the request open
    for it makes every client's timeout our problem -- the same reasoning
    `POST /optimize/analyze` records. Phase 10's WebSockets (C14) turn this into
    a live exchange; until then the client polls the URL returned here.

    The job is checked *now* rather than in the background, so a bad id fails
    with a precise status instead of being queued and failing where nobody is
    looking.
    """
    if payload.target_job_id is not None:
        job = await session.scalar(select(Job.id).where(Job.id == payload.target_job_id))
        if job is None:
            raise ResourceNotFoundError("Job")

    interview = Interview(
        id=uuid7(),
        user_id=user.id,
        target_role=payload.target_role.strip(),
        target_job_id=payload.target_job_id,
        question_budget=payload.question_budget,
    )
    session.add(interview)
    await session.commit()

    # Runs after the response is sent and opens its own session, because this
    # one closes with the request. Interim, like the resume pipeline: tasks die
    # with the process until Phase 10's queue (ADR-018).
    background.add_task(ask_next, interview.id)

    log.info(
        "interview created",
        interview_id=str(interview.id),
        user_id=str(user.id),
        role=interview.target_role,
        has_job=payload.target_job_id is not None,
    )
    return InterviewCreated(
        interview_id=interview.id,
        status=interview.status,
        poll_url=f"/api/v1/interviews/{interview.id}",
    )


@router.get(
    "/{interview_id}",
    response_model=InterviewRead,
    summary="An interview and everything asked in it",
    responses={404: {"model": ErrorResponse}},
)
async def read_interview(
    interview_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> InterviewRead:
    """The session, its questions, and why one is missing if it is.

    This is what US-8.1 AC2 means by resumable: the state machine lives in
    Postgres rather than in a model's context window, so closing the tab and
    returning tomorrow gives the same answer. It is also the poll target -- a
    question that has not arrived yet shows as a shorter `questions` list, and
    one that never will shows as `summary_feedback`.
    """
    interview = await _owned(session, interview_id, user.id)
    return InterviewRead.model_validate(interview)


@router.post(
    "/{interview_id}/questions/{question_id}/answer",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InterviewCreated,
    summary="Answer a question, and get the next one",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def answer_question(
    interview_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: AnswerSubmit,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
    submit: InterviewAnswerRunnerDep,
) -> InterviewCreated:
    """Record an answer; marking it and asking the next question follow.

    **The answer is written here, synchronously, before the 202.** Everything
    after it -- the mark, the policy's decision, the next question -- is a model
    call and goes to the background. But what the candidate actually typed is
    theirs, and losing it because a provider was slow would be the one
    unrecoverable failure in this feature.

    409 rather than 404 for a question already answered: the request is well
    formed and the resource exists, it is the state that refuses. `UNIQUE` on
    `interview_answers.question_id` enforces it in the database besides -- a
    second answer would give one question two scores and double its weight in
    the report.
    """
    interview = await _owned(session, interview_id, user.id)

    question = next((q for q in interview.questions if q.id == question_id), None)
    if question is None:
        # Scoped through the interview the caller owns, so a question id from
        # somebody else's session is indistinguishable from one that does not
        # exist.
        raise ResourceNotFoundError("Question")

    existing = await session.scalar(
        select(InterviewAnswer.id).where(InterviewAnswer.question_id == question_id)
    )
    if existing is not None:
        raise InvalidStateTransitionError("That question has already been answered.")

    session.add(
        InterviewAnswer(
            id=uuid7(),
            question_id=question_id,
            answer_text=payload.answer_text,
            duration_seconds=payload.duration_seconds,
            submitted_at=datetime.now(UTC),
        )
    )
    await session.commit()

    background.add_task(submit, question_id, payload.answer_text)

    log.info(
        "interview answer recorded",
        interview_id=str(interview_id),
        question_id=str(question_id),
        length=len(payload.answer_text),
    )
    return InterviewCreated(
        interview_id=interview_id,
        status=interview.status,
        poll_url=f"/api/v1/interviews/{interview_id}",
    )
