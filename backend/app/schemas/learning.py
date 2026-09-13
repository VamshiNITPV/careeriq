"""Learning path responses (US-5.2)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class LearningStepRead(BaseModel):
    position: int
    skill_id: uuid.UUID
    name: str
    severity: str
    #: Rough study hours for someone who already meets the prerequisites.
    #:
    #: An estimate, and named one deliberately. There is no dataset of how long
    #: people take to learn things, so the number is ordered sensibly against its
    #: neighbours and makes no claim to absolute accuracy.
    estimated_hours: int
    #: Something the reader can check they have done (US-5.2 AC2).
    #:
    #: Never a restatement of the skill name. "Understand Docker" is not an
    #: outcome; "containerise a service and run it with compose" is.
    outcome: str
    #: Steps in *this* path that must come first, by name.
    after: list[str]


class LearningPathResponse(BaseModel):
    steps: list[LearningStepRead]
    total_hours: int
    target_jobs: int
    target_roles: list[str]
    job_id: uuid.UUID | None = None
    #: Missing skills with no curated guidance, so the omission is visible.
    #:
    #: Reported rather than hidden: a plan silently shorter than the gap list is
    #: one a reader would assume is complete.
    skipped_uncurated: int = 0
    #: Why `steps` may be empty — mirrors `/skills/gaps`.
    #:
    #: NO_TARGET / NO_JOBS / READY.
    availability: str = "READY"
