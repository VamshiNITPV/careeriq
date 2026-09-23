"""Starting and resuming a mock interview (US-8.1).

Two routes. Creating one answers immediately and generates the first question
behind the response; reading one returns the whole transcript so far.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, InterviewRunnerDep
from app.core.exceptions import ResourceNotFoundError
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.models.interview import Interview
from app.models.job import Job
from app.schemas.common import ErrorResponse
from app.schemas.interview import InterviewCreate, InterviewCreated, InterviewRead

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
        .options(selectinload(Interview.questions))
        .where(Interview.id == interview_id, Interview.user_id == user_id)
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
