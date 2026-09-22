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

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ApplicationRepositoryDep, CurrentUser, DbSession
from app.api.v1.jobs import summary_of
from app.core.exceptions import InvalidStateTransitionError, ResourceNotFoundError
from app.core.logging import get_logger
from app.models.enums import ApplicationStatus
from app.schemas.application import ApplicationRead, ApplicationTransition
from app.schemas.application_list import ApplicationListItem, ApplicationListResponse
from app.schemas.common import ErrorResponse
from app.services.application import lifecycle
from app.services.application.transition import NothingLeftError, apply_transition

log = get_logger(__name__)

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


@router.patch(
    "/{application_id}/status",
    response_model=ApplicationRead,
    summary="Move an application to another stage",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def change_status(
    application_id: uuid.UUID,
    payload: ApplicationTransition,
    user: CurrentUser,
    session: DbSession,
    applications: ApplicationRepositoryDep,
) -> ApplicationRead:
    """Record that an application moved along the funnel (US-7.1).

    PATCH, not PUT. The body is one field of the resource rather than the whole
    of it, and unlike `PUT /jobs/{id}/application` this is **not idempotent** by
    design: repeating it is refused, because the second call asks to move from a
    status the application is already in and `allowed_from` deliberately excludes
    staying put. An event that records nothing happening is noise in a log whose
    entire worth is that every row means something happened.

    **409, not 422, for a disallowed move.** The request is well formed; it is
    the current state that refuses it. A 422 would send a client looking for a
    malformed body, and the fix — read the status again, it has moved — is a
    conflict resolution rather than a correction. Raised as
    `InvalidStateTransitionError`, which already existed for this: the code
    `INVALID_STATUS_TRANSITION` reaches the client inside the one error envelope
    every other endpoint uses (api.md 1.4), rather than FastAPI's own `detail`
    shape. `details.allowed` carries where the application *can* go, so a UI can
    rebuild its options from the error rather than hard-coding the funnel a
    second time and drifting from it.

    **404 covers both "no such application" and "not yours".** The repository
    scopes on `user_id`, so the two are indistinguishable here on purpose;
    answering 403 for somebody else's row would confirm it exists, which over a
    guessable id space is a membership oracle on other people's job hunts.

    Nothing advances on its own. Every move here is one the user reported, which
    is the same rule US-7.0 AC2 sets for the applied flag.
    """
    application = await applications.get_for_user(
        user_id=user.id, application_id=application_id
    )
    if application is None:
        raise ResourceNotFoundError("Application")

    try:
        apply_transition(
            session,
            application,
            target=payload.status,
            occurred_at=payload.occurred_at,
        )
    except lifecycle.IllegalTransitionError as exc:
        raise InvalidStateTransitionError(
            str(exc),
            details={
                "current": exc.current.value,
                "allowed": sorted(s.value for s in lifecycle.allowed_from(exc.current)),
            },
        ) from exc
    except NothingLeftError as exc:
        raise InvalidStateTransitionError(str(exc)) from exc

    # The route commits, not the service and not the repository -- the same
    # split the rest of the API uses, so one request is one transaction and the
    # status change cannot land without its event.
    await session.commit()
    await session.refresh(application)

    log.info(
        "application status changed",
        application_id=str(application.id),
        user_id=str(user.id),
        to_status=application.status.value,
    )
    return ApplicationRead.model_validate(application)
