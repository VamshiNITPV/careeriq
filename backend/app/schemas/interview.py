"""Starting and reading a mock interview (US-8.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InterviewStatus, QuestionDifficulty


class InterviewCreate(BaseModel):
    """The body of `POST /interviews`."""

    model_config = ConfigDict(extra="forbid")

    #: Free text, not an id. Somebody can rehearse for a role this corpus has
    #: never carried a posting for, and requiring a job to exist first would
    #: fail exactly the person preparing for something they have not found yet.
    target_role: str = Field(min_length=2, max_length=200)

    #: Optional, and the difference between a good interview and a better one.
    #:
    #: With it, questions are built from the posting's real requirements as well
    #: as the candidate's resume -- the overlap and the gaps between one person
    #: and one job. Without it, the role's aggregate demand stands in.
    target_job_id: uuid.UUID | None = None

    #: How many questions before it terminates.
    #:
    #: Bounded at both ends by the same reasoning the CHECK constraint uses: a
    #: budget of zero ends an interview before it starts, and one long enough to
    #: exhaust a free tier is not a kindness.
    question_budget: int = Field(default=10, ge=3, le=20)


class InterviewQuestionRead(BaseModel):
    """One question, as asked."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_order: int
    question_text: str
    topic: str
    difficulty: QuestionDifficulty
    #: The rubric an answer is marked against, shown because a candidate
    #: rehearsing alone deserves to know what a strong answer contains. It is
    #: written before the answer exists, so showing it cannot change the mark.
    expected_points: list[str]
    #: The resume words this was built on, if any. Shown so a candidate can see
    #: why they were asked this, and so the grounding claim is inspectable
    #: rather than taken on trust.
    grounded_in: str | None = None
    #: True when personalisation was rejected and this is the topic-only
    #: fallback -- a weaker question, and said so rather than passed off.
    degraded: bool = False
    asked_at: datetime | None = None


class InterviewRead(BaseModel):
    """A session and everything asked in it so far.

    This is what makes US-8.1 AC2's resumability real: the state lives in
    Postgres, so closing the tab and coming back tomorrow returns the same
    answer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_role: str
    target_job_id: uuid.UUID | None = None
    status: InterviewStatus
    current_difficulty: QuestionDifficulty
    topics_covered: list[str]
    questions_asked: int
    question_budget: int
    questions: list[InterviewQuestionRead]
    created_at: datetime

    #: Why no question arrived, when none has.
    #:
    #: The generation runs after the response is sent, so a failure has no
    #: request left to fail. Surfacing it here is the difference between "still
    #: thinking" and "this will never finish" -- and a client polling forever on
    #: the second is the failure mode worth designing against.
    summary_feedback: str | None = None


class InterviewCreated(BaseModel):
    """`POST /interviews` answers immediately; the first question follows."""

    interview_id: uuid.UUID
    status: InterviewStatus
    #: Where to poll. The model call takes seconds and holding the request open
    #: for it makes every client's timeout our problem -- the same reasoning
    #: `POST /optimize/analyze` records. Phase 10's WebSockets replace this.
    poll_url: str
