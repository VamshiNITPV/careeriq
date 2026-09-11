"""Job endpoints (api.md section 2.4)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AdminUser,
    ApplicationRepositoryDep,
    CurrentUser,
    DbSession,
    EmbeddingProviderDep,
    JobFetchRunRepositoryDep,
    JobProviderDep,
    JobServiceDep,
    MatchingServiceDep,
    ResumeVersionRepositoryDep,
)
from app.core.exceptions import (
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.logging import get_logger
from app.models.enums import EmploymentType, ExperienceLevel, WorkMode
from app.models.job import Job
from app.schemas.application import ApplicationRead, ApplicationStatusUpdate
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
    SimilarJob,
    SimilarJobsResponse,
)
from app.schemas.match import MatchDimension, MatchedSkill, MatchResponse, MatchSkills
from app.services.job.fetch import fetch_and_import
from app.services.job.pipeline import UnparseableJobError
from app.services.job.similar import find_similar
from app.services.matching.dimensions import SkillRequirementInput
from app.services.matching.recall import recall_jobs
from app.services.matching.recommend import rank_jobs
from app.services.matching.weights import RANKING_VERSION

log = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Import lives under /admin/jobs, as api.md section 2.4 specifies. That is also
# what keeps it away from `GET /jobs/{job_id}`: a sibling `/jobs/import` would
# be swallowed by the path parameter unless it were declared first, and relying
# on declaration order for correctness is a trap for whoever edits this next.
admin_router = APIRouter(prefix="/admin/jobs", tags=["admin"])


def summary_of(
    job: Job,
    *,
    application: ApplicationRead | None,
    match_score: Decimal | None = None,
) -> JobSummary:
    """A list row, plus what this caller has done about it.

    `application` is passed rather than read off the job: it is per-caller, and
    a relationship on the model would either need a user filter the ORM cannot
    express on a plain attribute or would load every user's rows.

    `match_score` is per-caller for the same reason, and defaults to None because
    most callers have not computed one. None means "not scored here", never
    "scores zero".
    """
    return JobSummary(
        application=application,
        match_score=match_score,
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


def _detail(job: Job, *, application: ApplicationRead | None = None) -> JobDetail:
    return JobDetail(
        **summary_of(job, application=application).model_dump(),
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


async def _match_sorted(
    *,
    user: CurrentUser,
    session: DbSession,
    service: JobServiceDep,
    matching: MatchingServiceDep,
    applications: ApplicationRepositoryDep,
    provider: EmbeddingProviderDep,
    query: str | None,
    work_mode: str | None,
    employment_type: str | None,
    experience_level: str | None,
    years_experience: Decimal | None,
    country_code: str | None,
    posted_within_days: int | None,
    limit: int,
    offset: int,
    min_score: Decimal | None,
    exclude_applied: bool,
) -> JobListResponse:
    """The browse list, ordered by match score instead of by date.

    Two-stage retrieval (ADR-006) with the browse filters pushed into stage one,
    so the ranking is computed over the filtered subset rather than computed over
    everything and filtered afterwards. The difference matters: recall is capped
    at 200, so filtering after ranking would show the remote jobs among the 200
    nearest — not the 200 nearest remote jobs.
    """
    chosen = await matching.default_resume_version_id(user.id)
    if chosen is None:
        return JobListResponse(
            items=[], total=0, limit=limit, offset=offset, availability="NO_RESUME"
        )
    if provider is None:
        return JobListResponse(
            items=[], total=0, limit=limit, offset=offset, availability="PENDING"
        )

    filters = {
        "query": query,
        "work_mode": work_mode,
        "employment_type": employment_type,
        "experience_level": experience_level,
        "years_experience": years_experience,
        "country_code": country_code,
        "posted_within_days": posted_within_days,
    }
    # Only when something is actually set. Unfiltered, this would bind every id
    # in the corpus as a parameter to express no restriction at all.
    allowed = (
        await service.jobs.ids_matching(**filters)  # type: ignore[arg-type]
        if any(value is not None and value != "" for value in filters.values())
        else None
    )

    recalled = await recall_jobs(
        session=session,
        user_id=user.id,
        resume_version_id=chosen,
        model_name=provider.model_name,
        exclude_applied=exclude_applied,
        allowed_job_ids=allowed,
    )
    if recalled is None:
        return JobListResponse(
            items=[], total=0, limit=limit, offset=offset, availability="PENDING"
        )

    ids = [row.job_id for row in recalled]
    # Carried forward from stage one rather than re-queried — the difference
    # between one round trip and 200 (see rank_jobs).
    cosines = {row.job_id: Decimal(str(row.similarity)) for row in recalled}
    by_id = {job.id: job for job in await service.get_many(ids)}
    ordered = [by_id[job_id] for job_id in ids if job_id in by_id]

    page = await rank_jobs(
        service=matching,
        user_id=user.id,
        resume_version_id=chosen,
        jobs=ordered,
        cosines=cosines,
        limit=limit,
        offset=offset,
        min_score=min_score,
    )

    live = await applications.for_jobs(
        user_id=user.id, job_ids=[result.job_id for result in page.items]
    )
    return JobListResponse(
        items=[
            summary_of(
                by_id[result.job_id],
                application=(
                    ApplicationRead.model_validate(live[result.job_id])
                    if result.job_id in live
                    else None
                ),
                match_score=result.overall_score,
            )
            for result in page.items
        ],
        # Bounded by RECALL_LIMIT, not a corpus count — the client's wording has
        # to say "matches", never "jobs".
        total=page.total,
        limit=limit,
        offset=offset,
        ranking_version=RANKING_VERSION,
    )


@router.get("", response_model=JobListResponse, summary="Browse jobs")
async def list_jobs(
    user: CurrentUser,
    service: JobServiceDep,
    # Needed only by `sort=match`, and injected unconditionally because FastAPI
    # resolves dependencies before the handler can know which branch it will
    # take. A session and three repositories are cheap; a session is opened for
    # every request on this router anyway.
    session: DbSession,
    matching: MatchingServiceDep,
    applications: ApplicationRepositoryDep,
    provider: EmbeddingProviderDep,
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
    posted_within_days: Annotated[
        int | None,
        Query(
            ge=1,
            le=365,
            description=(
                "Show postings published within this many days. Postings with no stated "
                "date are included — the provider often omits one, and a missing date "
                "says nothing about age."
            ),
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[
        Literal["recent", "match"],
        Query(description="`recent` is newest first; `match` ranks against your resume."),
    ] = "recent",
    min_score: Annotated[
        Decimal | None,
        Query(ge=0, le=100, description="Only with `sort=match`: hide jobs scoring below this."),
    ] = None,
    exclude_applied: Annotated[
        bool, Query(description="Only with `sort=match`: leave out jobs you have applied to.")
    ] = True,
) -> JobListResponse:
    """Live postings, newest first — or ranked against the caller's resume.

    Offset pagination rather than the cursor api.md specifies. The corpus is
    small and this list is ordered by a non-unique timestamp, so a cursor would
    have to encode a composite key to be stable — work worth doing when
    `/recommendations` needs it in Phase 6, over a ranking whose order is
    genuinely expensive to recompute per page.

    **`sort=match` is the same ranking `/recommendations` serves, reached through
    the browse filters.** It lives here rather than as filters bolted onto
    `/recommendations` because the browse list's page and filters live in its URL
    — `/jobs?work_mode=REMOTE&offset=20` restores the list exactly — and a cursor
    cannot be written into that URL. Folding the ranking into the endpoint that
    already has filters was the smaller change than giving the ranking endpoint
    filters, a total, and a second paging mode.

    Until this existed, "remote Python jobs, best match first" was not expressible
    anywhere: browse had every filter and no ranking, and `/recommendations` had
    the ranking and no filters.
    """
    if sort == "recent" and min_score is not None:
        # Rejected rather than ignored. Silently dropping it would return a
        # date-sorted list that looks like it honoured a score threshold, and the
        # caller has no way to see that it did not.
        raise ValidationError("min_score applies only when sort=match.")

    if sort == "match":
        return await _match_sorted(
            user=user,
            session=session,
            service=service,
            matching=matching,
            applications=applications,
            provider=provider,
            query=q,
            work_mode=work_mode.value if work_mode else None,
            employment_type=employment_type.value if employment_type else None,
            experience_level=experience_level.value if experience_level else None,
            years_experience=years_experience,
            country_code=country_code.upper() if country_code else None,
            posted_within_days=posted_within_days,
            limit=limit,
            offset=offset,
            min_score=min_score,
            exclude_applied=exclude_applied,
        )

    rows, total = await service.list_jobs(
        for_user_id=user.id,
        query=q,
        work_mode=work_mode.value if work_mode else None,
        employment_type=employment_type.value if employment_type else None,
        experience_level=experience_level.value if experience_level else None,
        years_experience=years_experience,
        country_code=country_code.upper() if country_code else None,
        posted_within_days=posted_within_days,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        items=[
            summary_of(job, application=ApplicationRead.model_validate(app) if app else None)
            for job, app in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    summary="Job detail with parsed structure and extracted skills",
    responses={404: {"model": ErrorResponse}},
)
async def get_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    service: JobServiceDep,
    applications: ApplicationRepositoryDep,
) -> JobDetail:
    """One posting.

    No ownership check, unlike resumes: the job corpus is shared. Anything a
    user submits becomes part of the market data every other user is ranked
    against, which is stated on the submission form.
    """
    job = await service.get_job(job_id)
    application = await applications.get_for_job(user_id=user.id, job_id=job_id)
    return _detail(
        job, application=ApplicationRead.model_validate(application) if application else None
    )


@router.put(
    "/{job_id}/application",
    response_model=ApplicationRead,
    summary="Save this job, or mark that you applied to it",
    responses={404: {"model": ErrorResponse}},
)
async def set_application(
    job_id: uuid.UUID,
    payload: ApplicationStatusUpdate,
    user: CurrentUser,
    service: JobServiceDep,
    applications: ApplicationRepositoryDep,
) -> ApplicationRead:
    """Record what the caller has done about this job (US-7.0).

    PUT rather than POST, and one endpoint rather than four. This is a singleton
    sub-resource — "the caller's application to this job" — so save, mark
    applied and unmark applied are all the same write with a different body,
    and the verb is idempotent by definition. A POST that 409s on the second tap
    is exactly the double-tap failure a bookmark on a phone must not have.

    **`saved` and `applied` are independent**, and the body carries both every
    time. A client that wants to mark a job applied sends the bookmark state it
    already has alongside it, so recording one fact can never silently rewrite
    the other — which is exactly what went wrong when this took a single status:
    ticking "applied" bookmarked the job too.

    `{saved: false, applied: false}` is a 422 from the schema. That is `DELETE`.

    200 always, never 201. The caller cannot tell a create from an update and
    does not need to, and varying the status by which one happened would make an
    idempotent endpoint's *response* non-idempotent — the property that makes
    retrying safe.

    The job is fetched first so an unknown id is a clean 404 rather than a
    RESTRICT violation surfacing through the catch-all as an opaque 500.
    """
    await service.get_job(job_id)
    application = await applications.upsert(
        user_id=user.id, job_id=job_id, saved=payload.saved, applied=payload.applied
    )
    log.info(
        "application recorded",
        job_id=str(job_id),
        user_id=str(user.id),
        status=application.status.value,
        is_saved=application.is_saved,
    )
    return ApplicationRead.model_validate(application)


@router.delete(
    "/{job_id}/application",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove this job from your saved list",
)
async def remove_application(
    job_id: uuid.UUID,
    user: CurrentUser,
    applications: ApplicationRepositoryDep,
) -> None:
    """Unsave a job. 204 whether or not there was anything to remove.

    Idempotent for the same reason the PUT is: a second tap on unsave must not
    become a visible error. That also means no 404 here — and no ownership check
    to write, because the delete is scoped by `(job_id, caller)` in its WHERE
    clause and is structurally incapable of touching another user's row.

    Soft, so the record that someone once applied survives them unsaving it.
    """
    await applications.soft_delete(user_id=user.id, job_id=job_id)


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


@router.get(
    "/{job_id}/similar",
    response_model=SimilarJobsResponse,
    summary="Jobs nearest this one by embedding",
    responses={404: {"model": ErrorResponse, "description": "No such job"}},
)
async def similar_jobs(
    job_id: uuid.UUID,
    user: CurrentUser,
    service: JobServiceDep,
    applications_repo: ApplicationRepositoryDep,
    provider: EmbeddingProviderDep,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> SimilarJobsResponse:
    """Nearest neighbours of this posting, by cosine distance over embeddings.

    The comparison happens entirely in SQL — the API never loads a model, which
    is what lets its image omit torch altogether (architecture.md's cold-start
    risk). The provider is injected only to learn *which* model's vectors to read,
    and is None when embeddings are switched off.

    Three distinguishable outcomes, because an empty list has three meanings:
    DISABLED when nothing is configured, PENDING when this posting has no vector
    yet, and READY when the comparison genuinely found nothing close enough.
    Collapsing them would make "no similar jobs" indistinguishable from "the
    feature is off", which is the sort of thing that gets debugged twice.
    """
    # 404s for an unknown id, and for another user's — the same check
    # GET /jobs/{id} makes, so the two cannot drift.
    await service.get_job(job_id)

    if provider is None:
        return SimilarJobsResponse(items=[], availability="DISABLED", limit=limit)

    rows = await find_similar(
        session=session,
        job_id=job_id,
        model_name=provider.model_name,
        limit=limit,
    )
    if rows is None:
        return SimilarJobsResponse(items=[], availability="PENDING", limit=limit)

    neighbours, model_name, model_version = rows
    if not neighbours:
        return SimilarJobsResponse(
            items=[],
            availability="READY",
            limit=limit,
            model_name=model_name,
            model_version=model_version,
        )

    ids = [job_id_ for job_id_, _ in neighbours]
    jobs = {job.id: job for job in await service.get_many(ids)}
    applications = await applications_repo.for_jobs(user_id=user.id, job_ids=ids)

    items = [
        SimilarJob(
            job=summary_of(
                jobs[found_id],
                application=(
                    ApplicationRead.model_validate(applications[found_id])
                    if found_id in applications
                    else None
                ),
            ),
            similarity=similarity,
        )
        # Ordered by the query, not by the dict — a mapping would lose the
        # ordering that is the entire result.
        for found_id, similarity in neighbours
        if found_id in jobs
    ]

    return SimilarJobsResponse(
        items=items,
        availability="READY",
        limit=limit,
        model_name=model_name,
        model_version=model_version,
    )


@router.get(
    "/{job_id}/match",
    response_model=MatchResponse,
    summary="How this caller matches this job",
    responses={404: {"model": ErrorResponse, "description": "No such job, or no such resume"}},
)
async def match_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    service: JobServiceDep,
    matching: MatchingServiceDep,
    resume_versions: ResumeVersionRepositoryDep,
    resume_version_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MatchResponse:
    """The six-dimension explainable score (US-4.1, US-4.2, ADR-005).

    Always 200. `availability` says what kind of answer this is, exactly as
    `/similar` does — an error status would claim something failed, and nothing
    did. `PARTIAL` is the honest and currently common case: every dimension but
    the semantic one ran, because one of the two vectors is not built yet.

    `NO_RESUME` returns a **null** score rather than the ~20 the neutral
    defaults would otherwise produce. A number computed entirely from "we don't
    know" is not a low score, it is a fabricated judgement about somebody the
    system has never seen (ADR-012).
    """
    # 404 before any work, and the same check GET /jobs/{id} makes so the two
    # cannot drift.
    job = await service.get_job(job_id)

    if resume_version_id is not None:
        # 404 rather than 403 for another user's resume: a 403 would confirm the
        # id exists, which is a membership oracle over other people's uploads.
        if await resume_versions.get_owned(resume_version_id, user.id) is None:
            raise ResourceNotFoundError("Resume version")
        chosen = resume_version_id
    else:
        chosen = await matching.default_resume_version_id(user.id)

    if chosen is None:
        return MatchResponse(job_id=job_id, availability="NO_RESUME")

    result = await matching.match(user_id=user.id, job=job, resume_version_id=chosen)

    return MatchResponse(
        job_id=job_id,
        availability="READY" if result.semantic_available else "PARTIAL",
        overall_score=result.overall_score,
        breakdown=[
            MatchDimension(
                dimension=row.dimension,
                score=row.score,
                weight=row.weight,
                contribution=row.contribution,
                status=row.status,
                reason=row.reason,
            )
            for row in result.breakdown
        ],
        scored_weight=result.scored_weight,
        skills=MatchSkills(
            matched=[_matched_skill(s) for s in result.skills.matched],
            partial=[_matched_skill(s) for s in result.skills.partial],
            missing=[_matched_skill(s) for s in result.skills.missing],
        ),
        ranking_version=result.ranking_version,
        resume_version_id=result.resume_version_id,
        computed_at=result.computed_at,
    )


def _matched_skill(skill: SkillRequirementInput) -> MatchedSkill:
    return MatchedSkill(id=skill.skill_id, name=skill.name, requirement=skill.requirement)


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
    fetch_runs: JobFetchRunRepositoryDep,
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
        posted_within_days=payload.posted_within_days,
    )

    # Recorded in the same ledger the scheduler reads. A manual fetch spends
    # from the same monthly quota, so leaving it out would let an admin's run
    # and the day's automatic runs each believe the budget was untouched.
    await fetch_runs.record(
        query=payload.query,
        country=payload.country,
        requests_spent=max(result.pages_fetched, 1),
        created=result.created,
        duplicates=result.duplicates,
        failed=len(result.failed),
        quota_remaining=result.quota_remaining,
        scheduled=False,
        stop_reason=result.stop_reason,
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
