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
from app.models.interview import (
    Interview,
    InterviewAnswer,
    InterviewQuestion,
    InterviewScore,
)
from app.models.job import Job
from app.models.resume import Resume, ResumeVersion
from app.services.interview.blueprint import blueprint_for
from app.services.interview.policy import GENERIC_TOPICS, InterviewState, Move, next_action
from app.services.interview.questions import QuestionRejected, generate_question
from app.services.interview.scoring import ScoreRejected, score_answer

log = get_logger(__name__)

#: What the policy is told before there is anything to react to.
#:
#: Sits inside ADR-013's middling band, which means "same rung, next topic" --
#: the only action that neither rewards nor punishes a candidate who has not
#: yet said anything.
MIDDLING_ENTRY = 0.5


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
    last_score: float | None = None,
    session: AsyncSession | None = None,
    provider: LLMProvider | None = None,
) -> None:
    """Generate and store the next question for this interview. Never raises.

    `session` and `provider` are injectable for the reason the resume pipeline's
    are: a test's rows live in an uncommitted transaction another connection
    cannot see, and a test must never call a real model.
    """
    if session is not None:
        await _run(session, interview_id, provider, last_score)
        return
    async with get_session_factory()() as own_session:
        await _run(own_session, interview_id, provider, last_score)


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
    session: AsyncSession,
    interview_id: uuid.UUID,
    provider: LLMProvider | None,
    last_score: float | None = None,
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
        if not posting_text:
            # Logged rather than passed over in silence. The candidate picked a
            # job; if its text contributed nothing they are owed a trace of why,
            # and `prompts.py` skips an empty posting with no signal at all. The
            # row can be gone (the FK is SET NULL) or genuinely empty.
            log.warning(
                "interview: targeted job has no description",
                interview_id=str(interview.id),
                job_id=str(interview.target_job_id),
            )

    # The blueprint is resolved per call rather than stored on the row. The
    # corpus grows, and an interview resumed next week should examine what the
    # market asks for then -- while `topics_covered` keeps the path already
    # walked, so nothing already asked gets asked again.
    blueprint = await blueprint_for(
        session, role=interview.target_role, job_id=interview.target_job_id
    )

    # Recorded on every resolution, not frozen at the first.
    #
    # The blueprint is deliberately re-resolved per call (see above), so a
    # session resumed next month can genuinely be drawing on a larger corpus
    # than it started with. A frozen column would then describe the first
    # question while the next one came from somewhere else -- and "from 3
    # postings" shown beside an interview now reading 40 looks like a bug rather
    # than history. The field means *what the most recent question was built
    # from*, and the schema says so.
    #
    # One column cannot describe a session that crossed a threshold mid-way.
    # Per-question provenance would, and is not worth a column until something
    # renders it.
    interview.topic_source = blueprint.source
    interview.topic_postings = blueprint.postings

    state = InterviewState(
        current_difficulty=interview.current_difficulty,
        topics_covered=tuple(interview.topics_covered),
        questions_asked=interview.questions_asked,
        question_budget=interview.question_budget,
        topics=blueprint.topics or GENERIC_TOPICS,
    )

    # The first question has no score to react to, so the policy is entered at
    # the middling band: same rung, next topic. Seeding it with a fake "good"
    # score would start every interview one rung harder than asked for, and a
    # fake bad one would open every interview with an apology.
    action = next_action(state, MIDDLING_ENTRY if last_score is None else last_score)
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


async def submit_answer(
    question_id: uuid.UUID,
    answer_text: str,
    *,
    session: AsyncSession | None = None,
    provider: LLMProvider | None = None,
) -> None:
    """Mark an answer already stored, and ask whatever comes next. Never raises.

    **This does not store the answer.** The route writes it synchronously before
    its 202, because what the candidate typed is theirs and losing it to a slow
    provider would be the one unrecoverable failure in this feature. By the time
    this runs, the row exists; `answer_text` is passed in rather than re-read
    only to save a query.

    That division is worth stating plainly because the name does not carry it,
    and a caller who reads "submit" as "store" gets a scoring task against an
    answer that is not there. `duration_seconds` used to be a parameter here for
    the same reason -- it looked like this function's business, it was written by
    the route, and nothing ever read the copy passed down.

    Marking, the policy's decision and the next question are one background task
    rather than three, because from the candidate's side they are one event:
    they answered, and the next question should appear. Splitting them would
    make a half-finished turn -- answered but unscored -- a state the UI has to
    render and the policy has to tolerate.
    """
    if session is not None:
        await _answer(session, question_id, answer_text, provider)
        return
    async with get_session_factory()() as own_session:
        await _answer(own_session, question_id, answer_text, provider)


async def _answer(
    session: AsyncSession,
    question_id: uuid.UUID,
    answer_text: str,
    provider: LLMProvider | None,
) -> None:
    question = await session.scalar(
        select(InterviewQuestion)
        .options(selectinload(InterviewQuestion.interview))
        .where(InterviewQuestion.id == question_id)
    )
    if question is None:  # pragma: no cover - checked by the route first
        return
    interview = question.interview

    llm = provider if provider is not None else get_llm_provider()
    if llm is None:
        await _fail(session, interview, "Scoring needs an AI provider, which is not configured.")
        return

    try:
        marked = await score_answer(
            llm,
            question_text=question.question_text,
            expected_points=list(question.expected_points),
            answer_text=answer_text,
            target_role=interview.target_role,
        )
    except ScoreRejected as exc:
        # The answer is already stored by the route, so nothing the candidate
        # typed is lost. Only the mark is missing, and saying so beats inventing
        # a number -- there is no sensible default for "how good was this", and
        # 0.5 would be a fabrication with a confident face.
        await _fail(session, interview, f"Could not mark that answer: {exc}")
        return
    except Exception:
        # Deliberately broad, as above: this runs after the response has gone.
        log.exception("interview: scoring failed", question_id=str(question_id))
        await _fail(session, interview, "The AI provider could not be reached just now.")
        return

    # What the policy decides next, recorded *with the score* rather than
    # recomputed later. The policy can change, and a report read in a month
    # should show the decision actually taken (US-8.2 AC2).
    state = InterviewState(
        current_difficulty=interview.current_difficulty,
        topics_covered=tuple(interview.topics_covered),
        questions_asked=interview.questions_asked,
        question_budget=interview.question_budget,
    )
    action = next_action(state, float(marked.overall))

    session.add(
        InterviewScore(
            id=uuid7(),
            answer_id=(await _answer_row(session, question_id)).id,
            technical_score=marked.dimensions["technical"],
            relevance_score=marked.dimensions["relevance"],
            completeness_score=marked.dimensions["completeness"],
            communication_score=marked.dimensions["communication"],
            structure_score=marked.dimensions["structure"],
            overall_score=marked.overall,
            feedback=marked.feedback,
            strengths=list(marked.strengths),
            improvements=list(marked.improvements),
            cited_spans=[
                {"start": s.start, "end": s.end, "text": s.text, "note": s.note}
                for s in marked.cited_spans
            ],
            next_difficulty=action.difficulty,
            scored_by=marked.model,
        )
    )
    interview.summary_feedback = None
    await session.commit()

    log.info(
        "interview: answer scored",
        question_id=str(question_id),
        overall=str(marked.overall),
        move=action.move.value,
        citations=len(marked.cited_spans),
    )

    # And on to the next, driven by the score that was just recorded.
    await _run(session, interview.id, provider, float(marked.overall))


async def _answer_row(session: AsyncSession, question_id: uuid.UUID) -> InterviewAnswer:
    row = await session.scalar(
        select(InterviewAnswer).where(InterviewAnswer.question_id == question_id)
    )
    if row is None:  # pragma: no cover - the route writes it before queueing
        raise RuntimeError("The answer vanished between its write and its scoring.")
    return row
