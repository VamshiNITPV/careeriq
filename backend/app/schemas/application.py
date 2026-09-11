"""Saved-job and applied-flag primitives (US-7.0).

Deliberately imports nothing from `schemas.job`. `JobSummary` embeds
`ApplicationRead`, so anything here that reached back for a job schema would be
an import cycle Pydantic cannot resolve. The types that *do* embed a job — the
profile lists — live in `schemas.application_list`, which is free to import
both.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import ApplicationStatus


class ApplicationStatusUpdate(BaseModel):
    """The body of `PUT /jobs/{job_id}/application`.

    **Two independent flags, not one status.** They used to be a single enum
    holding SAVED *or* APPLIED, which made "I bookmarked this" and "I applied to
    this" mutually exclusive — so marking a job applied silently bookmarked it.
    Sending both every time also makes this a true PUT: the body is the complete
    desired state, so a client cannot leave half of it behind by accident.

    Defaults to `saved=True, applied=False`, so a bare `{}` still means "save
    this" — which is what the bookmark sends, and what keeps the body optional.

    `saved=False, applied=False` is refused (422). That request means "I have no
    relationship to this job", which is what `DELETE` already says, and one
    meaning should not have two routes.
    """

    # `extra="forbid"` so the old `{"status": "APPLIED"}` body is a 422 rather
    # than being quietly ignored — which is what Pydantic does by default, and
    # it turned "I applied" into "I saved" with nothing failing. A stale client
    # getting a clear error beats it silently recording the wrong fact, which is
    # the same class of quiet wrongness this split exists to end.
    model_config = ConfigDict(extra="forbid")

    saved: bool = True
    applied: bool = False

    @model_validator(mode="after")
    def _must_mean_something(self) -> ApplicationStatusUpdate:
        if not self.saved and not self.applied:
            raise ValueError(
                "A job must be saved, applied to, or both. "
                "Use DELETE to remove it from your list entirely."
            )
        return self


class ApplicationRead(BaseModel):
    """What the calling user has done about one job.

    Embedded in `JobSummary` as a nullable field *and* returned whole by the
    PUT — the same shape in both directions, so the client swaps one field
    rather than translating between two representations.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    status: ApplicationStatus
    #: Whether the user bookmarked this job.
    #:
    #: Independent of `status`: a job can be bookmarked, applied to, or both.
    #: The client reads *this* for the bookmark icon — reading "does a row
    #: exist" instead is what made applying fill the bookmark.
    is_saved: bool
    #: Non-null exactly when status is APPLIED, which the applied_has_timestamp
    #: CHECK enforces in both directions.
    applied_at: datetime | None = None
    #: When it was saved. Orders the profile lists.
    created_at: datetime
