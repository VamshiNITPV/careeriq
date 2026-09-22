"""Saved-job and applied-flag primitives (US-7.0).

Deliberately imports nothing from `schemas.job`. `JobSummary` embeds
`ApplicationRead`, so anything here that reached back for a job schema would be
an import cycle Pydantic cannot resolve. The types that *do* embed a job — the
profile lists — live in `schemas.application_list`, which is free to import
both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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


class ApplicationTransition(BaseModel):
    """The body of `PATCH /applications/{id}/status` (US-7.1).

    Separate from `ApplicationStatusUpdate` above, which is two booleans about a
    job. This is one move along the funnel, and the two are not the same write:
    that one is idempotent and says "here is the complete state", this one asks
    for a *change* and is refused if the funnel does not allow it.
    """

    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus

    #: When it actually happened, if that is not now.
    #:
    #: Optional because most moves are recorded as they happen, and required to
    #: be expressible because many are not — people log an interview the evening
    #: after it. `application_events.occurred_at` is a separate column from
    #: `created_at` for exactly this reason, and an endpoint that could not set
    #: it would make that column always equal the other one.
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def _not_in_the_future(self) -> ApplicationTransition:
        # A funnel measures elapsed time between events. One dated ahead of now
        # produces negative durations, and the arithmetic downstream has no way
        # to tell that from a bug in itself.
        if self.occurred_at is not None and self.occurred_at > datetime.now(UTC):
            raise ValueError("occurred_at cannot be in the future.")
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
    #: When the user says they applied. NULL while the row is only a bookmark.
    #:
    #: The `applied_has_timestamp` CHECK ties this to `status` in both
    #: directions: NULL when SAVED, set for every stage past it, and unconstrained
    #: once REJECTED or WITHDRAWN — an application can stop before it was ever
    #: sent. (This used to read "non-null exactly when status is APPLIED", which
    #: was true of the two-state funnel and became wrong when US-7.1 widened it.)
    applied_at: datetime | None = None
    #: When it was saved. Orders the profile lists.
    created_at: datetime
