"""The caller's saved and applied jobs (US-7.0).

Only the list lives here. The writes are a sub-resource of a job — `PUT` and
`DELETE /jobs/{job_id}/application` — and stay on the jobs router beside the
resource they belong to.

This module *does* carry `from __future__ import annotations`, unlike
`api/v1/career.py`. That file omits it because its routes are built by a factory
and their bodies are annotated with a loop variable; a hand-written router has no
such problem, and copying the omission without the reason is what its comment
exists to prevent.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ApplicationRepositoryDep, CurrentUser
from app.api.v1.jobs import summary_of
from app.models.enums import ApplicationStatus
from app.schemas.application_list import ApplicationListItem, ApplicationListResponse

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=ApplicationListResponse, summary="Jobs you saved or applied to")
async def list_applications(
    user: CurrentUser,
    applications: ApplicationRepositoryDep,
    status: Annotated[ApplicationStatus | None, Query()] = None,
) -> ApplicationListResponse:
    """Everything the caller has saved, newest first.

    The profile page asks for all of them and splits the two lists client-side
    rather than making two filtered requests: the lists are one question and
    entries move between them, so two responses could disagree and leave a row
    in both or in neither. `status` exists for callers that want one list.

    Not paginated. This is a personal list bounded by how many jobs one person
    saves, unlike the shared corpus.
    """
    rows = await applications.list_for_user(user_id=user.id, status=status)

    return ApplicationListResponse(
        items=[
            ApplicationListItem(
                id=row.id,
                job_id=row.job_id,
                status=row.status,
                is_saved=row.is_saved,
                applied_at=row.applied_at,
                created_at=row.created_at,
                # application=None inside: this row already is the application,
                # and a second copy nested in its own job could disagree with
                # this one after the client updates it.
                job=summary_of(row.job, application=None),
            )
            for row in rows
        ],
        total=len(rows),
    )
