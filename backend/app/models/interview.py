"""The adaptive mock interview and its transcript (database.md section 3.8).

Four tables, and the shape of them is ADR-013's argument made concrete: **the
interview's state lives here, not in an LLM's context window.**

    interviews ──< interview_questions ──< interview_answers ──< interview_scores

That matters twice over. It is what makes a session resumable (US-8.1 AC2) —
close the tab, come back tomorrow, and `current_difficulty` and `topics_covered`
are still true. And it is what makes the adaptation logic testable without a
model at all: `services/interview/policy.py` reads these columns and returns the
next action, so the trajectory can be proven exhaustively offline while the
model is only ever asked to write question text.

The alternative ADR-013 rejects — letting the model carry its own state across
turns — is "unreliable, unauditable, and grows the context window until it
degrades or costs too much". Every column below is a piece of state that would
otherwise have to be re-read out of a transcript and trusted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InterviewStatus, QuestionDifficulty


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Reference a native enum the migration owns.

    `create_type=False` is load-bearing: without it SQLAlchemy emits CREATE TYPE
    on every table create and the migration fails on the second run. Same helper
    and same reason as `models/application.py`.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class Interview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One mock interview session, and the state machine driving it."""

    __tablename__ = "interviews"
    __table_args__ = (
        # The budget is what terminates the interview. Zero would mean a session
        # that ends before it starts, and a negative one would never terminate
        # under a `questions_asked >= budget` check -- a loop bounded by a number
        # nothing stops from going the wrong way.
        CheckConstraint("question_budget > 0", name="ck_interviews_budget_positive"),
        CheckConstraint("questions_asked >= 0", name="ck_interviews_asked_not_negative"),
        Index("ix_interviews_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    #: Optional link to the application this was practice for.
    #:
    #: SET NULL, not CASCADE: deleting an application must not delete the record
    #: that you practised for it, for the same reason database.md gives about
    #: analytics losing data quietly.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )

    #: Free text, not a foreign key. An interview can be practice for a role the
    #: corpus has never carried a posting for, and requiring a job to exist
    #: first would make the feature useless to exactly the person rehearsing for
    #: something they have not found yet.
    target_role: Mapped[str] = mapped_column(Text, nullable=False)
    target_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[InterviewStatus] = mapped_column(
        _pg_enum(InterviewStatus, "interview_status"),
        nullable=False,
        default=InterviewStatus.CREATED,
        server_default=text("'CREATED'::interview_status"),
    )

    # ------------------------------------------------- the state machine (ADR-013)
    #
    # These two are the machine. Everything else on the row is provenance or a
    # result; these are what `next_action` reads and writes, and what a resumed
    # session restores itself from.
    current_difficulty: Mapped[QuestionDifficulty] = mapped_column(
        _pg_enum(QuestionDifficulty, "question_difficulty"),
        nullable=False,
        default=QuestionDifficulty.MEDIUM,
        server_default=text("'MEDIUM'::question_difficulty"),
    )
    #: Topics already asked about, so the policy does not circle.
    #:
    #: `default=list` alongside `server_default` is not redundant, for the reason
    #: `models/profile.py` records: the server default only applies to rows the
    #: database inserts, and `expire_on_commit=False` means a Python-constructed
    #: object holds None until re-read — which then fails to serialise.
    topics_covered: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )

    question_budget: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=10, server_default=text("10")
    )
    questions_asked: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )

    # ------------------------------------------------- the report
    #
    # All null until the interview completes. Null means "not finished", never
    # "scored zero" -- the distinction the whole codebase keeps making.
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    #: The five dimensions, averaged across answers.
    #:
    #: JSONB rather than five columns: this is a computed summary of
    #: `interview_scores`, which already holds the dimensions as real columns.
    #: Two authoritative copies in different shapes is how they come to disagree.
    dimension_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    questions: Mapped[list[InterviewQuestion]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="InterviewQuestion.question_order",
    )


class InterviewQuestion(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One question asked, and the rubric its answer will be judged against."""

    __tablename__ = "interview_questions"
    __table_args__ = (
        # Without this a retry can write two question 3s, and the transcript has
        # no order -- which breaks the report, the resume-where-you-left-off
        # read, and the difficulty trajectory US-8.2 AC2 asks to display.
        Index(
            "ux_interview_questions_order",
            "interview_id",
            "question_order",
            unique=True,
        ),
    )

    interview_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    question_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        _pg_enum(QuestionDifficulty, "question_difficulty"), nullable=False
    )

    #: What a good answer covers. The rubric, stored with the question.
    #:
    #: Written when the question is generated, not when the answer is scored,
    #: and that ordering is the point: `ml.md` section 7.1 has the model judge
    #: "against stated criteria rather than a vague impression", which only
    #: holds if the criteria were fixed before the answer existed.
    expected_points: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )

    #: The candidate's own words this question was built on, verified present
    #: in the resume before the question was stored.
    #:
    #: Kept rather than discarded after checking. It is the evidence for the
    #: claim -- "this was built on your line about the ledger migration" is
    #: showable, and a grounding nobody can inspect afterwards is a grounding
    #: nobody can audit. Null when the question builds on nothing specific,
    #: which is allowed.
    grounded_in: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: True when the personalised attempts were rejected and this is the
    #: topic-only fallback.
    #:
    #: Stored, not merely logged. `questions.py` promises a report can say the
    #: personalisation did not hold, and a promise kept in a log file is not
    #: kept -- the report reads rows.
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    #: Which model wrote it. A question generated by a model that has since been
    #: replaced is still a valid question, and a report is only interpretable if
    #: it says what produced it (ADR-007).
    generated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    interview: Mapped[Interview] = relationship(back_populates="questions")
    answer: Mapped[InterviewAnswer | None] = relationship(
        back_populates="question", cascade="all, delete-orphan", uselist=False
    )


class InterviewAnswer(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """What the user said. One per question, enforced."""

    __tablename__ = "interview_answers"

    #: UNIQUE, and the constraint is doing real work. `interview_scores` hangs
    #: off the answer, so a second answer to one question would give that
    #: question two scores and silently double its weight in the report.
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("interview_questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: How long they took. Not scored -- a slow answer is not a worse one -- but
    #: it is the kind of thing a person reviewing their own transcript wants.
    duration_seconds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    question: Mapped[InterviewQuestion] = relationship(back_populates="answer")
    score: Mapped[InterviewScore | None] = relationship(
        back_populates="answer", cascade="all, delete-orphan", uselist=False
    )


class InterviewScore(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """How one answer scored, on five dimensions (US-8.3 AC1)."""

    __tablename__ = "interview_scores"
    __table_args__ = (
        # Every dimension is a 0.0-1.0 fraction. A score outside that range is
        # not a low or high score, it is a parsing failure -- and it would
        # travel straight into the averages and the agreement metric without
        # this, looking like a result.
        CheckConstraint(
            "technical_score BETWEEN 0 AND 1 AND relevance_score BETWEEN 0 AND 1 "
            "AND completeness_score BETWEEN 0 AND 1 AND communication_score BETWEEN 0 AND 1 "
            "AND structure_score BETWEEN 0 AND 1 AND overall_score BETWEEN 0 AND 1",
            name="ck_interview_scores_in_range",
        ),
        CheckConstraint(
            "human_score IS NULL OR human_score BETWEEN 0 AND 1",
            name="ck_interview_scores_human_in_range",
        ),
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("interview_answers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    technical_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    relevance_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    completeness_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    communication_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    structure_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    improvements: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )

    #: Character offsets into the answer text (US-8.3 AC2).
    #:
    #: Offsets rather than quoted excerpts, so a citation cannot drift from what
    #: was actually said. A quote is a copy the model could paraphrase without
    #: anybody noticing; an offset either lands on the user's own words or is
    #: out of range and detectably wrong.
    cited_spans: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    #: What the policy decided next, recorded so the trajectory is auditable.
    #:
    #: Stored rather than recomputed: the policy can change, and a report read a
    #: month later should show the decision that was actually taken, not the one
    #: today's code would take (US-8.2 AC2).
    next_difficulty: Mapped[QuestionDifficulty | None] = mapped_column(
        _pg_enum(QuestionDifficulty, "question_difficulty"), nullable=True
    )
    scored_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: A human's score for the same answer. Null except on evaluation rows.
    #:
    #: On this row rather than in a spreadsheet, which database.md section 3.8
    #: calls deliberate: model-vs-human agreement becomes one query instead of a
    #: join against a file nobody versioned. ADR-015 requires that number before
    #: this feature can claim to work, and US-8.3 AC3 is what it satisfies.
    human_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    answer: Mapped[InterviewAnswer] = relationship(back_populates="score")
