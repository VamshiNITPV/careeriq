"""The profile lists: applications with the jobs they are about.

Separate from `schemas.application` because these embed a `JobSummary`, and
`JobSummary` embeds an `ApplicationRead` — putting both directions in one module
is an import cycle. The primitives sit one level down and this imports both.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.application import ApplicationRead
from app.schemas.job import JobSummary


class ApplicationListItem(ApplicationRead):
    """One row of "Saved jobs" or "Applications".

    `job.application` is always null here. The row already *is* the application,
    and serialising it a second time inside its own job would give the client two
    copies that can disagree the moment it updates one of them.
    """

    job: JobSummary


class ApplicationListResponse(BaseModel):
    items: list[ApplicationListItem]
    total: int
