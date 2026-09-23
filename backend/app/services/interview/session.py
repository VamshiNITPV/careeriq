"""Running an interview: asking the next question and storing it.

This is where the three pure pieces meet a database. `blueprint.py` says what to
examine, `policy.py` says which topic and rung come next, `questions.py` writes
and gates the text. None of those three knows this module exists, which is what
keeps all three testable without one.

## It never raises

Called from a `BackgroundTasks`, after the response has already gone. An
exception here reaches nobody -- there is no request left to fail -- so a
failure is *recorded on the row* instead, where the polling client can see it.
The same arrangement `resume/optimization.py` uses and for the same reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session_factory
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.integrations.llm import get_llm_provider
from app.integrations.llm.base import LLMProvider
from app.models.enums import InterviewStatus
from app.models.interview import Interview, InterviewQuestion
from app.models.job import Job
from app.models.resume import Resume, ResumeVersion
from app.services.interview.blueprint import blueprint_for
from app.services.interview.policy import GENERIC_TOPICS, InterviewState, Move, next_action
from app.services.interview.questions import QuestionRejected, generate_question

log = get_logger(__name__)


async def _resume_text(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The user's current resume text, or None if they have none parsed.

    The primary resume's current version, else the newest -- the same rule
    `MatchingRepository.default_resume_version_id` applies, so an interview and
    a match score talk about the same document.
    """
    row = await session.scalar(
        select(ResumeVersion.raw_text)
        .join(Resume, Resume.current_version_id == ResumeVersion.id)
        .where(Resume.user_id == user_id, Resume.deleted_at.is_(None))
        .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
        .limit(1)
    )
    return row


async def ask_next_question(
    interview_id: uuid.UUID,
    *,
    session: AsyncSession | None = None,
    provider: LLMProvider | None = None,
) -> None:
    """Generate and store the next question for this interview. Never raises.

    `session` and `provider` are injectable for the reason the resume pipeline's
    are: a test's rows live in an uncommitted transaction another connection
    cannot see, and a test must never call a real model.
    """
    if session is not None:
        await _run(session, interview_id, provider)
        return
    async with get_session_factory()() as own_session:
        await _run(own_session, interview_id, provider)


async def _fail(session: AsyncSession, interview: Interview, reason: str) -> None:
    """Record why no question arrived, where the client can read it.

    `summary_feedback` rather than a new column: it is the row's one free-text
    field and an interview that could not start has nothing else to say. The
    status stays CREATED, so a retry is still possible -- this is not ABANDONED,
    which means the user walked away.
    """
    interview.summary_feedback = reason
    await session.commit()
    log.warning("interview: no question generated", interview_id=str(interview.id), reason=reason)


async def _run(
    session: AsyncSession, interview_id: uuid.UUID, provider: LLMProvider | None
) -> None:
    interview = await session.scalar(
        select(Interview)
        .options(selectinload(Interview.questions))
        .where(Interview.id == interview_id)
    )
    if interview is None:  # pragma: no cover - the row was just written
        log.warning("interview: vanished before its first question", id=str(interview_id))
        return

    llm = provider if provider is not None else get_llm_provider()
    if llm is None:
        # LLM_PROVIDER=none is a valid deployment, and this feature simply does
        # not work without one. Said plainly rather than left as an empty
        # interview the user waits on forever.
        await _fail(
            session,
            interview,
            "Mock interviews need an AI provider, which is not configured.",
        )
        return

    resume_text = await _resume_text(session, interview.user_id)
    if not resume_text:
        await _fail(
            session,
            interview,
            "Upload and process a resume first -- the questions are built from it.",
        )
        return

    posting_text = None
    if interview.target_job_id is not None:
        posting_text = await session.scalar(
            select(Job.description_raw).where(Job.id == interview.target_job_id)
        )

    # The blueprint is resolved per call rather than stored on the row. The
    # corpus grows, and an interview resumed next week should examine what the
    # market asks for then -- while `topics_covered` keeps the path already
    # walked, so nothing already asked gets asked again.
    blueprint = await blueprint_for(session, role=interview.target_role)

    state = InterviewState(
        current_difficulty=interview.current_difficulty,
        topics_covered=tuple(interview.topics_covered),
        questions_asked=interview.questions_asked,
        question_budget=interview.question_budget,
        topics=blueprint.topics or GENERIC_TOPICS,
    )

    # The first question has no score to react to, so the policy is entered at
    # the middling band: same rung, next topic. Seeding it with a fake "good"
    # score would start every interview one rung harder than asked for.
    action = next_action(state, 0.5)
    if action.move is Move.FINISH or action.topic is None or action.difficulty is None:
        interview.status = InterviewStatus.COMPLETED
        interview.completed_at = datetime.now(UTC)
        await session.commit()
        return

    try:
        generated = await generate_question(
            llm,
            topic=action.topic,
            difficulty=action.difficulty,
            target_role=interview.target_role,
            resume_text=resume_text,
            posting_text=posting_text,
        )
    except QuestionRejected as exc:
        await _fail(session, interview, f"Could not produce a usable question: {exc}")
        return
    # Deliberately broad: this runs after the response has gone, so anything
    # escaping here reaches no caller and would leave the interview looking
    # stuck forever. The reason is recorded on the row instead.
    except Exception:
        log.exception("interview: question generation failed", interview_id=str(interview.id))
        await _fail(session, interview, "The AI provider could not be reached just now.")
        return

    session.add(
        InterviewQuestion(
            id=uuid7(),
            interview_id=interview.id,
            question_order=interview.questions_asked + 1,
            question_text=generated.question_text,
            topic=generated.topic,
            difficulty=generated.difficulty,
            expected_points=list(generated.expected_points),
            grounded_in=generated.grounded_in,
            degraded=generated.degraded,
            generated_by=generated.model,
            asked_at=datetime.now(UTC),
        )
    )

    # The state advances only once a question actually exists. A failed
    # generation that had already incremented the counter would burn a question
    # from the budget without asking one.
    interview.questions_asked += 1
    interview.current_difficulty = generated.difficulty
    if generated.topic not in interview.topics_covered:
        # Reassigned rather than mutated: SQLAlchemy does not track in-place
        # changes to a plain ARRAY, so `.append` here writes nothing and the
        # policy would revisit the same topic forever.
        interview.topics_covered = [*interview.topics_covered, generated.topic]
    if interview.status is InterviewStatus.CREATED:
        interview.status = InterviewStatus.IN_PROGRESS
        interview.started_at = datetime.now(UTC)
    interview.summary_feedback = None

    await session.commit()
    log.info(
        "interview: question asked",
        interview_id=str(interview.id),
        order=interview.questions_asked,
        topic=generated.topic,
        difficulty=generated.difficulty.value,
        degraded=generated.degraded,
    )
