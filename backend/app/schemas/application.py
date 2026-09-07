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

from pydantic import BaseModel, ConfigDict

from app.models.enums import ApplicationStatus


class ApplicationStatusUpdate(BaseModel):
    """The body of `PUT /jobs/{job_id}/application`.

    Defaults to SAVED, so a bare `{}` means "save this" — which is what the
    bookmark sends and what makes the request body optional in practice.
    """

    status: ApplicationStatus = ApplicationStatus.SAVED


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
    #: Non-null exactly when status is APPLIED, which the applied_has_timestamp
    #: CHECK enforces in both directions.
    applied_at: datetime | None = None
    #: When it was saved. Orders the profile lists.
    created_at: datetime
