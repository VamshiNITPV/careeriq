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
    #: The reader has ticked this off.
    #:
    #: A finished step stays in the plan rather than vanishing: the list is a
    #: route being walked, and dropping the finished parts would remove the only
    #: evidence of progress there is.
    completed: bool = False


class LearningPathResponse(BaseModel):
    steps: list[LearningStepRead]
    total_hours: int
    #: Hours left once finished steps are discounted.
    #:
    #: Alongside `total_hours`, not instead of it. "180 of 677 hours remaining"
    #: says something that "180 hours" alone does not.
    remaining_hours: int = 0
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


class StepCompletionUpdate(BaseModel):
    """Body of the tick-off toggle.

    A boolean rather than two verbs, so the request states the desired end state
    and repeating it changes nothing — the same shape the save-a-job toggle uses,
    for the same reason: this is a checkbox someone taps twice on a phone.
    """

    completed: bool
