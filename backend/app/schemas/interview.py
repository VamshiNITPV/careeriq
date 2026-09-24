"""Starting and reading a mock interview (US-8.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InterviewStatus, InterviewTopicSource, QuestionDifficulty


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


class AnswerSubmit(BaseModel):
    """The body of `POST /interviews/{id}/questions/{qid}/answer`."""

    model_config = ConfigDict(extra="forbid")

    answer_text: str = Field(min_length=1, max_length=20_000)
    #: How long they took. Not scored -- a slow answer is not a worse one -- but
    #: it is the kind of thing somebody reviewing their own transcript wants.
    duration_seconds: int | None = Field(default=None, ge=0, le=7_200)


class CitedSpanRead(BaseModel):
    """A part of the answer the feedback points at (US-8.3 AC2)."""

    #: Character offsets into the answer, verified to lie inside it before this
    #: was stored. A citation that points somewhere other than where it says is
    #: worse than none, because it will be believed.
    start: int
    end: int
    text: str
    note: str = ""


class AnswerScoreRead(BaseModel):
    """How one answer was marked (US-8.3 AC1)."""

    model_config = ConfigDict(from_attributes=True)

    technical_score: Decimal
    relevance_score: Decimal
    completeness_score: Decimal
    communication_score: Decimal
    structure_score: Decimal
    #: The mean of the five. Computed here rather than asked of the model, so
    #: the parts and the whole cannot disagree.
    overall_score: Decimal
    feedback: str | None = None
    strengths: list[str]
    improvements: list[str]
    cited_spans: list[CitedSpanRead] | None = None
    #: What the policy decided next, stored when the score was. The policy can
    #: change; a report read in a month should show the decision actually taken
    #: (US-8.2 AC2).
    next_difficulty: QuestionDifficulty | None = None


class InterviewAnswerRead(BaseModel):
    """What the candidate said, and how it was marked."""

    model_config = ConfigDict(from_attributes=True)

    answer_text: str
    duration_seconds: int | None = None
    submitted_at: datetime | None = None
    score: AnswerScoreRead | None = None


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
    #: Null until answered. The pair is the transcript.
    answer: InterviewAnswerRead | None = None


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
    #: Which of the three sources produced the topics of the **latest** question,
    #: and how many postings it read. Null until the first question exists.
    #:
    #: Surfaced so the interface can say what it actually did instead of always
    #: claiming market demand -- "from this posting", "from 12 postings for this
    #: role" and "a general list" are three different promises, and two of them
    #: were being made in the other's name.
    #:
    #: Latest rather than first: the blueprint is re-resolved per question, so a
    #: resumed session can cross a threshold mid-way. One field cannot describe
    #: both ends of that, and describing the question about to be asked is the
    #: more useful half.
    topic_source: InterviewTopicSource | None = None
    topic_postings: int | None = None
    questions: list[InterviewQuestionRead]
    created_at: datetime

    #: Why no question arrived, when none has.
    #:
    #: The generation runs after the response is sent, so a failure has no
    #: request left to fail. Surfacing it here is the difference between "still
    #: thinking" and "this will never finish" -- and a client polling forever on
    #: the second is the failure mode worth designing against.
    summary_feedback: str | None = None


class InterviewSummary(BaseModel):
    """One row of "your interviews", without the transcript.

    Deliberately not `InterviewRead`. A list of ten sessions, each carrying
    every question, answer, score and cited span, is a large response to render
    a page of headings from -- and the transcript is one click away.
    """

    id: uuid.UUID
    target_role: str
    status: InterviewStatus
    questions_asked: int
    question_budget: int
    #: How many have been answered, which is not `questions_asked`: the last
    #: question is asked and unanswered for as long as somebody is thinking.
    answered: int
    #: Mean of the overall marks so far, or null when nothing is marked yet.
    #:
    #: Null rather than 0.0, for the reason the scorer refuses to invent a mark:
    #: an interview nobody has answered has no score, and 0.0 would read as
    #: having done badly at it.
    average_score: Decimal | None = None
    topic_source: InterviewTopicSource | None = None
    #: The posting this was practice for, when there was one.
    #:
    #: Two fields rather than an embedded `JobSummary`: that carries eighteen of
    #: them plus a nested application, which is a lot of payload to render one
    #: line, and it would contradict this model's own reason for existing. The
    #: title is not repeated either -- `target_role` already *is* the job title
    #: on both job-backed paths, and a second copy could only disagree.
    target_job_id: uuid.UUID | None = None
    target_company: str | None = None
    created_at: datetime


class InterviewListResponse(BaseModel):
    items: list[InterviewSummary]
    total: int


class InterviewCreated(BaseModel):
    """`POST /interviews` answers immediately; the first question follows."""

    interview_id: uuid.UUID
    status: InterviewStatus
    #: Where to poll. The model call takes seconds and holding the request open
    #: for it makes every client's timeout our problem -- the same reasoning
    #: `POST /optimize/analyze` records. Phase 10's WebSockets replace this.
    poll_url: str
