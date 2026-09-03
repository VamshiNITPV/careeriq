"""Resume endpoints (api.md section 2.3)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, status
from fastapi.responses import Response

from app.api.deps import (
    CandidateSkillRepositoryDep,
    CurrentUser,
    PipelineRunnerDep,
    ResumeServiceDep,
    SkillRepositoryDep,
)
from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.models.enums import ProcessingStatus
from app.models.resume import Resume
from app.repositories.resume import LatestVersion
from app.schemas.common import ErrorResponse, MessageResponse
from app.schemas.resume import (
    ProcessingStatusResponse,
    ResumeDetail,
    ResumeRead,
    ResumeUpdateRequest,
    ResumeUploadResponse,
    ResumeVersionDetail,
    ResumeVersionSummary,
    SuggestedSkill,
    SuggestionsResponse,
)
from app.services.file_validation import MAX_UPLOAD_BYTES, validate_upload

log = get_logger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

# Coarse progress per stage. Presented as an estimate rather than a measurement,
# because tracking real progress through a parser would mean instrumenting
# pdfplumber for a number nobody acts on.
_STAGE: dict[ProcessingStatus, tuple[int, str]] = {
    ProcessingStatus.PENDING: (5, "Queued"),
    ProcessingStatus.EXTRACTING: (30, "Reading the document"),
    ProcessingStatus.PARSING: (65, "Finding sections and skills"),
    # Reserved. The pipeline never assigns EMBEDDING today — the real path is
    # PENDING → EXTRACTING → PARSING → COMPLETE — so a user has never seen this
    # label. Kept because the enum member and the migration both exist and
    # ADR-010 specifies the stage; delete all three together or none.
    ProcessingStatus.EMBEDDING: (85, "Generating embeddings"),
    ProcessingStatus.COMPLETE: (100, "Complete"),
    ProcessingStatus.FAILED: (100, "Failed"),
}

# Statuses that mean a pipeline run is already under way for this version.
_IN_FLIGHT = (
    ProcessingStatus.PENDING,
    ProcessingStatus.EXTRACTING,
    ProcessingStatus.PARSING,
    ProcessingStatus.EMBEDDING,
)


def _to_read(
    resume: Resume, *, skill_count: int = 0, latest: LatestVersion | None = None
) -> ResumeRead:
    """Build the list/detail representation of a resume.

    One helper rather than three call sites, because the three used to disagree:
    the list computed skill_count while detail and update hardcoded zero, and
    the delete dialog's "N skills will be removed" copy reads that number.
    """
    return ResumeRead.model_validate(resume).model_copy(
        update={
            "skill_count": skill_count,
            "latest_version_id": latest.id if latest is not None else None,
            "latest_version_status": latest.processing_status if latest is not None else None,
            "latest_version_error": latest.processing_error if latest is not None else None,
        }
    )


def _latest_of(resume: Resume) -> LatestVersion | None:
    """Latest version from an already-loaded relationship.

    Resume.versions is ordered desc(version_number), so the newest is first.
    Used by the detail endpoints in preference to a second query, which also
    means the summary fields cannot contradict the `versions` array shipped
    alongside them.
    """
    if not resume.versions:
        return None
    newest = resume.versions[0]
    return LatestVersion(
        id=newest.id,
        version_number=newest.version_number,
        processing_status=newest.processing_status,
        processing_error=newest.processing_error,
    )


@router.post(
    "",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a resume",
    responses={
        413: {"model": ErrorResponse, "description": "File exceeds 5 MB"},
        415: {"model": ErrorResponse, "description": "Not a PDF or DOCX"},
        409: {"model": ErrorResponse, "description": "Resume limit reached"},
    },
)
async def upload_resume(
    user: CurrentUser,
    service: ResumeServiceDep,
    background: BackgroundTasks,
    run_pipeline: PipelineRunnerDep,
    file: Annotated[UploadFile, File(description="PDF or DOCX, max 5 MB")],
    title: Annotated[str | None, Form()] = None,
    resume_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ResumeUploadResponse:
    """Accept a resume and parse it in the background (ADR-009).

    Returns 202 immediately. Validation runs *before* accepting, so a bad file
    fails here with a precise status rather than being queued and failing
    invisibly in a worker (US-2.1 AC4).
    """
    content = await file.read()

    # Type is determined from the bytes; the filename and the client-supplied
    # content type are both attacker-controlled and are not consulted
    # (ADR-014).
    upload = validate_upload(content=content, filename=file.filename)

    resume, version, is_duplicate = await service.upload(
        user_id=user.id, upload=upload, title=title, resume_id=resume_id
    )

    if not is_duplicate:
        # FastAPI runs this after the response is sent. It is an interim
        # mechanism: tasks die with the process, which is why the queue in
        # Phase 10 replaces it (ADR-018). The pipeline opens its own session
        # because the request's session closes with the response.
        background.add_task(run_pipeline, version.id)

    return ResumeUploadResponse(
        resume_id=resume.id,
        version_id=version.id,
        status=version.processing_status,
        is_duplicate=is_duplicate,
        poll_url=f"/api/v1/resumes/versions/{version.id}/status",
    )


@router.get("", response_model=list[ResumeRead], summary="List your resumes")
async def list_resumes(user: CurrentUser, service: ResumeServiceDep) -> list[ResumeRead]:
    resumes = await service.list_resumes(user.id)
    counts = await service.skill_counts(user_id=user.id)
    latest = await service.latest_versions(resume_ids=[r.id for r in resumes])

    return [
        _to_read(r, skill_count=counts.get(r.id, 0), latest=latest.get(r.id)) for r in resumes
    ]


@router.get(
    "/versions/{version_id}/status",
    response_model=ProcessingStatusResponse,
    summary="Processing progress for a version",
    responses={404: {"model": ErrorResponse}},
)
async def version_status(
    version_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> ProcessingStatusResponse:
    """Poll for progress.

    The documented fallback for WebSockets (ADR-010), and the only mechanism
    until Phase 10 adds the socket. Wasteful compared with a push, but it works
    everywhere and needs no connection handling.
    """
    version = await service.get_version(version_id=version_id, user_id=user.id)
    # .get, not [], so that adding a ProcessingStatus member cannot 500 this
    # endpoint mid-poll and leave the page spinning forever.
    percent, label = _STAGE.get(version.processing_status, (0, "Processing"))

    return ProcessingStatusResponse(
        version_id=version.id,
        status=version.processing_status,
        percent=percent,
        stage_label=label,
        error=version.processing_error,
        is_terminal=version.processing_status
        in (ProcessingStatus.COMPLETE, ProcessingStatus.FAILED),
    )


@router.get(
    "/versions/{version_id}/suggestions",
    response_model=SuggestionsResponse,
    summary="Skills the resume demonstrates but does not name",
    responses={404: {"model": ErrorResponse}},
)
async def version_suggestions(
    version_id: uuid.UUID,
    user: CurrentUser,
    service: ResumeServiceDep,
    skills: SkillRepositoryDep,
    candidate_skills: CandidateSkillRepositoryDep,
) -> SuggestionsResponse:
    """Return inferred skills for the user to confirm or discard.

    Separate from the extracted skills on purpose. "Built responsive user
    interfaces" is evidence of Responsive Web Design, but the candidate never
    claimed that skill — we interpreted it. Writing it to their profile
    automatically would be the system inventing something about them, which
    ADR-012 forbids.

    Each suggestion carries the sentence it came from, so the user judges the
    reasoning rather than a bare label. Confirming one is an ordinary
    POST /profile/skills, which marks it user-verified like any manual addition.
    """
    version = await service.get_version(version_id=version_id, user_id=user.id)
    entities = version.parsed_entities or {}

    # Suggestions are computed once at parse time and stored, but whether one
    # is still worth showing depends on the profile *now*. Filtering here rather
    # than at parse time is what stops an accepted suggestion reappearing on
    # every refresh, asking the user to add what they just added.
    on_profile = await candidate_skills.names_for_user(user.id)

    raw = [s for s in entities.get("suggested_skills", []) if s["name"] not in on_profile]
    resolved = await skills.get_by_names([s["name"] for s in raw])

    return SuggestionsResponse(
        version_id=version.id,
        suggestions=[
            SuggestedSkill(
                skill_id=resolved[s["name"]].id if s["name"] in resolved else None,
                name=s["name"],
                confidence=Decimal(str(s["confidence"])),
                evidence=s["evidence"],
                section=s["section"],
            )
            for s in raw
        ],
        unknown_terms=entities.get("unknown_terms", []),
    )


@router.post(
    "/versions/{version_id}/reparse",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run parsing on an already-uploaded file",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Already being processed"},
    },
)
async def reparse_version(
    version_id: uuid.UUID,
    user: CurrentUser,
    service: ResumeServiceDep,
    background: BackgroundTasks,
    run_pipeline: PipelineRunnerDep,
) -> ResumeUploadResponse:
    """Parse the stored file again with the current extractor.

    The taxonomy and the parser improve over time, and a resume uploaded last
    week was parsed by last week's version. Without this, the only way to pick
    up an improvement is to re-upload the same file — which also creates a
    pointless second version.

    Corrections survive: the upsert refuses to overwrite any skill marked
    user-verified (US-2.4 AC2), so re-parsing adds newly recognised skills
    without reverting anything edited by hand.
    """
    version = await service.get_version(version_id=version_id, user_id=user.id)

    if version.processing_status in _IN_FLIGHT:
        # Without this, a second run starts on its own session and the two
        # interleave their status commits — so a poller watches the progress bar
        # rewind from "Finding sections" back to "Reading the document", and
        # both runs upsert skills concurrently. The client disables the button
        # while it polls; this covers the other tab and the retried request.
        raise ConflictError(
            "That resume is already being processed. Wait for it to finish before trying again.",
            code="ALREADY_PROCESSING",
        )

    # The pipeline short-circuits on COMPLETE for idempotency, so a re-run has
    # to reset the status explicitly. Committed here for the same reason the
    # upload commits: the worker runs on its own connection.
    version.processing_status = ProcessingStatus.PENDING
    version.processing_error = None
    await service.versions.commit()

    background.add_task(run_pipeline, version.id)

    return ResumeUploadResponse(
        resume_id=version.resume_id,
        version_id=version.id,
        status=ProcessingStatus.PENDING,
        is_duplicate=False,
        poll_url=f"/api/v1/resumes/versions/{version.id}/status",
    )


@router.get(
    "/versions/{version_id}",
    response_model=ResumeVersionDetail,
    summary="Parsed content of one version",
    responses={404: {"model": ErrorResponse}},
)
async def get_version(
    version_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> ResumeVersionDetail:
    version = await service.get_version(version_id=version_id, user_id=user.id)
    return ResumeVersionDetail.model_validate(version)


@router.get(
    "/versions/{version_id}/download",
    summary="Download the original file",
    responses={404: {"model": ErrorResponse}},
    response_class=Response,
)
async def download_version(
    version_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> Response:
    content, filename, mime_type = await service.download(version_id=version_id, user_id=user.id)
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            # The filename is quoted and was sanitised on upload. An unescaped
            # one containing a quote or newline would let a crafted upload
            # inject arbitrary response headers.
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Belt and braces: never let a browser sniff a stored file into
            # something executable.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{resume_id}",
    response_model=ResumeDetail,
    summary="Resume detail with version history",
    responses={404: {"model": ErrorResponse}},
)
async def get_resume(
    resume_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> ResumeDetail:
    resume = await service.get_resume(resume_id=resume_id, user_id=user.id)
    counts = await service.skill_counts(user_id=user.id)
    return ResumeDetail(
        **_to_read(
            resume, skill_count=counts.get(resume.id, 0), latest=_latest_of(resume)
        ).model_dump(),
        versions=[ResumeVersionSummary.model_validate(v) for v in resume.versions],
    )


@router.get(
    "/{resume_id}/versions",
    response_model=list[ResumeVersionSummary],
    summary="Version history",
    responses={404: {"model": ErrorResponse}},
)
async def list_versions(
    resume_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> list[ResumeVersionSummary]:
    resume = await service.get_resume(resume_id=resume_id, user_id=user.id)
    return [ResumeVersionSummary.model_validate(v) for v in resume.versions]


@router.patch(
    "/{resume_id}",
    response_model=ResumeRead,
    summary="Rename or set primary",
    responses={404: {"model": ErrorResponse}},
)
async def update_resume(
    resume_id: uuid.UUID,
    payload: ResumeUpdateRequest,
    user: CurrentUser,
    service: ResumeServiceDep,
) -> ResumeRead:
    if payload.title is not None:
        await service.rename(resume_id=resume_id, user_id=user.id, title=payload.title)
    if payload.is_primary is True:
        resume = await service.set_primary(resume_id=resume_id, user_id=user.id)
    else:
        resume = await service.get_resume(resume_id=resume_id, user_id=user.id)
    counts = await service.skill_counts(user_id=user.id)
    return _to_read(resume, skill_count=counts.get(resume.id, 0), latest=_latest_of(resume))


@router.delete(
    "/{resume_id}",
    response_model=MessageResponse,
    summary="Delete a resume",
    responses={404: {"model": ErrorResponse}},
)
async def delete_resume(
    resume_id: uuid.UUID, user: CurrentUser, service: ResumeServiceDep
) -> MessageResponse:
    await service.delete(resume_id=resume_id, user_id=user.id)
    return MessageResponse(message="Resume deleted.")


@router.get("/limits/upload", summary="Upload constraints", include_in_schema=False)
async def upload_limits() -> dict[str, object]:
    """Lets the client show limits without duplicating the numbers."""
    return {
        "max_bytes": MAX_UPLOAD_BYTES,
        "accepted_types": ["application/pdf", "docx"],
    }
