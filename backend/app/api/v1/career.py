"""Work history, education, project and certification endpoints.

US-2.4 AC1 — every extracted field is editable. Extraction is heuristic reading
of wildly variable layouts, so it will be wrong sometimes; without an edit path
a wrong row is permanent, and it is scored against every job the user sees.

Built from one factory rather than four hand-written routers. The four types
differ only in their schemas and their repository, and four copies of the same
create/update/delete logic is four places for the `is_user_verified` rule to
drift.
"""

# NO `from __future__ import annotations` in this module, unlike every other
# file here — and it must stay that way.
#
# The routes below are built by a factory, so their request bodies are annotated
# with the *variable* `create`, not a literal class name. Postponed evaluation
# would turn that into the string "create", which FastAPI then hands to Pydantic
# as an unresolvable forward reference: every route registers fine and the app
# only fails when something asks for the OpenAPI schema. Without the import, the
# annotation is evaluated at definition time, when `create` is bound to the
# actual class.

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ResourceNotFoundError
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.models.career import Certification, EducationRecord, Project, WorkExperience
from app.repositories.career import (
    CareerEntityRepository,
    CertificationRepository,
    EducationRepository,
    ProjectRepository,
    WorkExperienceRepository,
)
from app.schemas.career import (
    CareerSummary,
    CertificationCreate,
    CertificationRead,
    CertificationUpdate,
    EducationCreate,
    EducationRead,
    EducationUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    WorkExperienceCreate,
    WorkExperienceRead,
    WorkExperienceUpdate,
)
from app.schemas.common import ErrorResponse, MessageResponse
from app.services.resume.entities import (
    certification_key,
    education_key,
    experience_key,
    project_key,
)

log = get_logger(__name__)

router = APIRouter(prefix="/profile", tags=["career"])


def _register(
    *,
    path: str,
    noun: str,
    model: type[Any],
    repository: Callable[[Any], CareerEntityRepository[Any]],
    read: type[BaseModel],
    create: type[BaseModel],
    update: type[BaseModel],
    key_for: Callable[[dict[str, Any]], str],
) -> None:
    """Add list / create / update / delete for one entity type."""

    @router.get(
        path,
        response_model=list[read],  # type: ignore[valid-type]
        name=f"list_{noun}",
        summary=f"List your {noun}",
    )
    async def list_entities(user: CurrentUser, session: DbSession) -> Any:
        return await repository(session).list_for_user(user.id)

    @router.post(
        path,
        response_model=read,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{noun}",
        summary=f"Add a {noun[:-1] if noun.endswith('s') else noun} by hand",
    )
    async def create_entity(payload: create, user: CurrentUser, session: DbSession) -> Any:  # type: ignore[valid-type]
        data = payload.model_dump()  # type: ignore[attr-defined]
        entity = model(
            id=uuid7(),
            user_id=user.id,
            # No source version: this was never about a particular document, so
            # it survives any resume being deleted.
            source_version_id=None,
            content_key=key_for(data),
            # The user asserted this. A later parse may not overwrite it.
            is_user_verified=True,
            **data,
        )
        session.add(entity)
        await session.flush()
        await session.refresh(entity)
        return entity

    @router.patch(
        path + "/{entity_id}",
        response_model=read,
        name=f"update_{noun}",
        summary=f"Correct a {noun[:-1] if noun.endswith('s') else noun}",
        responses={404: {"model": ErrorResponse}},
    )
    async def update_entity(
        entity_id: uuid.UUID, payload: update, user: CurrentUser, session: DbSession
    ) -> Any:  # type: ignore[valid-type]
        entity = await _owned(repository(session), entity_id, user.id)

        # exclude_unset: an absent field must stay as it is. Without it a
        # one-field PATCH arrives with every other field set to None and wipes
        # the row.
        for key, value in payload.model_dump(exclude_unset=True).items():  # type: ignore[attr-defined]
            setattr(entity, key, value)

        # content_key is deliberately NOT recomputed. It identifies the entity
        # to the parser, not to the reader: changing it because the user tidied
        # a company name would leave the next parse with no match, and it would
        # insert a second row alongside the corrected one.
        entity.is_user_verified = True

        await session.flush()
        await session.refresh(entity)
        return entity

    @router.delete(
        path + "/{entity_id}",
        response_model=MessageResponse,
        name=f"delete_{noun}",
        summary=f"Remove a {noun[:-1] if noun.endswith('s') else noun}",
        responses={404: {"model": ErrorResponse}},
    )
    async def delete_entity(
        entity_id: uuid.UUID, user: CurrentUser, session: DbSession
    ) -> MessageResponse:
        entity = await _owned(repository(session), entity_id, user.id)
        await session.delete(entity)
        return MessageResponse(message="Removed.")


async def _owned(
    repository: CareerEntityRepository[Any], entity_id: uuid.UUID, user_id: uuid.UUID
) -> Any:
    """Fetch only if this user owns it.

    404 rather than 403 when it belongs to someone else — a 403 confirms the id
    exists and lets an attacker enumerate (US-1.5 AC1).
    """
    entity = await repository.get(entity_id)
    if entity is None or entity.user_id != user_id:
        raise ResourceNotFoundError("Entry")
    return entity


_register(
    path="/experience",
    noun="experiences",
    model=WorkExperience,
    repository=WorkExperienceRepository,
    read=WorkExperienceRead,
    create=WorkExperienceCreate,
    update=WorkExperienceUpdate,
    key_for=lambda d: experience_key(d["title"], d.get("company_name"), d.get("start_date")),
)

_register(
    path="/education",
    noun="education",
    model=EducationRecord,
    repository=EducationRepository,
    read=EducationRead,
    create=EducationCreate,
    update=EducationUpdate,
    key_for=lambda d: education_key(d["institution"], d.get("degree"), d.get("end_date")),
)

_register(
    path="/projects",
    noun="projects",
    model=Project,
    repository=ProjectRepository,
    read=ProjectRead,
    create=ProjectCreate,
    update=ProjectUpdate,
    key_for=lambda d: project_key(d["name"]),
)

_register(
    path="/certifications",
    noun="certifications",
    model=Certification,
    repository=CertificationRepository,
    read=CertificationRead,
    create=CertificationCreate,
    update=CertificationUpdate,
    key_for=lambda d: certification_key(d["name"], d.get("issuer")),
)


@router.get(
    "/career",
    response_model=CareerSummary,
    summary="Everything the resume produced, in one response",
)
async def career_summary(user: CurrentUser, session: DbSession) -> CareerSummary:
    """All four types together.

    The profile page renders them on one screen, and four round trips to fill
    it is four chances for a partial render.
    """
    return CareerSummary(
        experiences=[
            WorkExperienceRead.model_validate(row)
            for row in await WorkExperienceRepository(session).list_for_user(user.id)
        ],
        education=[
            EducationRead.model_validate(row)
            for row in await EducationRepository(session).list_for_user(user.id)
        ],
        projects=[
            ProjectRead.model_validate(row)
            for row in await ProjectRepository(session).list_for_user(user.id)
        ],
        certifications=[
            CertificationRead.model_validate(row)
            for row in await CertificationRepository(session).list_for_user(user.id)
        ],
    )
