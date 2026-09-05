"""Job endpoints (api.md section 2.4)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, JobProviderDep, JobServiceDep
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.logging import get_logger
from app.models.enums import EmploymentType, ExperienceLevel, WorkMode
from app.models.job import Job
from app.schemas.common import ErrorResponse
from app.schemas.job import (
    CompanyRead,
    ImportFailureRead,
    JobApplicationLinkUpdate,
    JobDetail,
    JobFetchRequest,
    JobFetchResponse,
    JobImportRequest,
    JobImportResponse,
    JobListResponse,
    JobSkillRead,
    JobSubmitRequest,
    JobSubmitResponse,
    JobSummary,
)
from app.services.job.fetch import fetch_and_import
from app.services.job.pipeline import UnparseableJobError

log = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Import lives under /admin/jobs, as api.md section 2.4 specifies. That is also
# what keeps it away from `GET /jobs/{job_id}`: a sibling `/jobs/import` would
# be swallowed by the path parameter unless it were declared first, and relying
# on declaration order for correctness is a trap for whoever edits this next.
admin_router = APIRouter(prefix="/admin/jobs", tags=["admin"])


def _summary(job: Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        company=CompanyRead.model_validate(job.company) if job.company is not None else None,
        location=job.location,
        country_code=job.country_code,
        work_mode=job.work_mode,
        employment_type=job.employment_type,
        experience_level=job.experience_level,
        min_years_experience=job.min_years_experience,
        max_years_experience=job.max_years_experience,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        salary_period=job.salary_period,
        posted_at=job.posted_at,
        created_at=job.created_at,
        skill_count=len(job.skills),
    )


def _detail(job: Job) -> JobDetail:
    return JobDetail(
        **_summary(job).model_dump(),
        source=job.source,
        source_url=job.source_url,
        status=job.status,
        description_raw=job.description_raw,
        responsibilities=job.responsibilities,
        requirements=job.requirements,
        benefits=job.benefits,
        min_education=job.min_education,
        expires_at=job.expires_at,
        skills=[
            JobSkillRead(
                skill_id=js.skill_id,
                name=js.skill.name,
                requirement=js.requirement,
                min_years=js.min_years,
                extraction_confidence=js.extraction_confidence,
            )
            # REQUIRED first, then by confidence: the reason to open a posting is
            # to see what it demands, not what it would merely like.
            for js in sorted(
                job.skills,
                key=lambda s: (
                    s.requirement.value != "REQUIRED",
                    -(float(s.extraction_confidence or 0)),
                    s.skill.name,
                ),
            )
        ],
    )


@router.post(
    "",
    response_model=JobSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a job by pasting its description",
    responses={422: {"model": ErrorResponse, "description": "Not parseable as a posting"}},
)
async def submit_job(
    payload: JobSubmitRequest, user: CurrentUser, service: JobServiceDep
) -> JobSubmitResponse:
    """Parse a pasted description into a structured job (US-3.1).

    201, not the 202 api.md sketches. Parsing here is regex over text with no
    I/O — single-digit milliseconds — so there is nothing to defer, and the
    interim background runner (ADR-018) strands rows when the process restarts.
    The user gets the parsed result in this response instead of polling for it.
    Phase 6 adds embeddings, which is the point at which this genuinely needs a
    queue.

    A posting already in the corpus returns the existing job with
    `is_duplicate: true` rather than creating a second row (US-3.2 AC2).
    """
    try:
        result = await service.submit(
            raw_text=payload.description,
            user_id=user.id,
            title=payload.title,
            company_name=payload.company,
            source_url=payload.source_url,
        )
    except UnparseableJobError as exc:
        # 422: the request was well-formed, its content just is not a job
        # posting. The message is written for the person who pasted it.
        raise ValidationError(exc.message) from exc

    return JobSubmitResponse(job=_detail(result.job), is_duplicate=result.is_duplicate)


@router.get("", response_model=JobListResponse, summary="Browse jobs")
async def list_jobs(
    user: CurrentUser,
    service: JobServiceDep,
    q: Annotated[str | None, Query(max_length=200, description="Title or description text")] = None,
    work_mode: WorkMode | None = None,
    employment_type: EmploymentType | None = None,
    experience_level: ExperienceLevel | None = None,
    years_experience: Annotated[
        Decimal | None,
        Query(
            ge=0,
            le=60,
            decimal_places=1,
            description="Show jobs whose stated experience range covers this many years.",
        ),
    ] = None,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    """Live postings, newest first.

    Offset pagination rather than the cursor api.md specifies. The corpus is
    small and this list is ordered by a non-unique timestamp, so a cursor would
    have to encode a composite key to be stable — work worth doing when
    `/recommendations` needs it in Phase 6, over a ranking whose order is
    genuinely expensive to recompute per page.
    """
    jobs, total = await service.list_jobs(
        query=q,
        work_mode=work_mode.value if work_mode else None,
        employment_type=employment_type.value if employment_type else None,
        experience_level=experience_level.value if experience_level else None,
        years_experience=years_experience,
        country_code=country_code.upper() if country_code else None,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[_summary(job) for job in jobs], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    summary="Job detail with parsed structure and extracted skills",
    responses={404: {"model": ErrorResponse}},
)
async def get_job(job_id: uuid.UUID, user: CurrentUser, service: JobServiceDep) -> JobDetail:
    """One posting.

    No ownership check, unlike resumes: the job corpus is shared. Anything a
    user submits becomes part of the market data every other user is ranked
    against, which is stated on the submission form.
    """
    return _detail(await service.get_job(job_id))


@router.patch(
    "/{job_id}/application-link",
    response_model=JobDetail,
    summary="Attach an application link to a job that has none",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "It already has one"},
    },
)
async def set_application_link(
    job_id: uuid.UUID,
    payload: JobApplicationLinkUpdate,
    user: CurrentUser,
    service: JobServiceDep,
) -> JobDetail:
    """Fill in a missing "Apply for this job" link.

    A sub-resource rather than a general `PATCH /jobs/{id}`: the corpus is
    shared, and a generic job PATCH is an invitation to grow into an editor of
    everyone else's data. This one field, and only while it is empty.

    Any signed-in user may do it, for the same reason `GET /{job_id}` has no
    ownership check — the corpus belongs to everybody. 409, not 404, when a link
    is already there: the 403-confirms-existence rule is about ownership, and
    there is none here, so hiding the conflict would only stop the client doing
    the useful thing, which is re-fetching and showing the link that now exists.

    Returns the whole job so the client updates from this response rather than
    firing a second GET, as `PATCH /profile` does.
    """
    return _detail(
        await service.set_application_link(
            job_id=job_id, source_url=payload.source_url, actor_user_id=user.id
        )
    )


@admin_router.post(
    "/fetch",
    response_model=JobFetchResponse,
    summary="Pull current postings from the configured jobs provider",
    responses={
        403: {"model": ErrorResponse, "description": "Admin only"},
        503: {"model": ErrorResponse, "description": "No jobs provider configured"},
    },
)
async def fetch_jobs(
    payload: JobFetchRequest,
    admin: AdminUser,
    service: JobServiceDep,
    provider: JobProviderDep,
) -> JobFetchResponse:
    """Ingest live postings from a permitted jobs API (US-3.4).

    200 with a per-page-and-per-posting report, for the same reason
    `/import` does it: a partial result is the normal outcome, and the count of
    rejected postings *is* the signal about provider quality. A provider that
    truncates descriptions shows up here as `created: 0` with a page of
    identical "too short" reasons, rather than as a quietly short result.

    Synchronous because the work is bounded and predictable — at most five
    network round trips, each parse single-digit milliseconds. Anything larger
    needs the queue that does not exist until Phase 10 (ADR-008, ADR-018).

    Re-running the same fetch creates nothing (AC1): every posting carries the
    provider's own id, namespaced as `provider:id`, and `(source, external_id)`
    is unique. A repeat therefore costs quota but not correctness — which is
    also the interim answer to the `Idempotency-Key` header api.md section 1.8
    specifies and nothing yet implements.

    Note `created` under-reports in one case: when a fetched posting matches an
    existing linkless row by content hash, its link is attached to that row and
    it is counted as a duplicate. That is a quiet improvement to the corpus, not
    a lost posting.
    """
    if provider is None:
        raise ServiceUnavailableError(
            "No jobs provider is configured. Set JOBS_PROVIDER and JOBS_API_KEY."
        )

    result = await fetch_and_import(
        provider=provider,
        service=service,
        query=payload.query,
        country=payload.country,
        max_pages=payload.max_pages,
    )

    return JobFetchResponse(
        provider=result.provider,
        created=result.created,
        duplicates=result.duplicates,
        failed=[
            ImportFailureRead(index=f.index, external_id=f.external_id, reason=f.reason)
            for f in result.failed
        ],
        processed=result.processed,
        pages_fetched=result.pages_fetched,
        postings_seen=result.postings_seen,
        stopped_early=result.stopped_early,
        stop_reason=result.stop_reason,
        quota_remaining=result.quota_remaining,
    )


@admin_router.post(
    "/import",
    response_model=JobImportResponse,
    summary="Bulk-import a job dataset",
    responses={403: {"model": ErrorResponse, "description": "Admin only"}},
)
async def import_jobs(
    payload: JobImportRequest, admin: AdminUser, service: JobServiceDep
) -> JobImportResponse:
    """Import a batch of postings (US-3.3).

    Returns 200 with a per-record report rather than failing on the first bad
    row (AC2). A partial success is the normal outcome for a real dataset, and
    an operator needs to know *which* records failed and why — a 400 with no
    detail would mean bisecting the file by hand.

    Re-running the same batch creates nothing new (AC1), because every record
    carries an `external_id` that is unique per source.
    """
    result = await service.import_batch([record.model_dump() for record in payload.records])

    return JobImportResponse(
        created=result.created,
        duplicates=result.duplicates,
        failed=[
            ImportFailureRead(index=f.index, external_id=f.external_id, reason=f.reason)
            for f in result.failed
        ],
        processed=result.processed,
    )
