"""Recommendation endpoints (api.md section 2.5, US-4.1).

Two-stage retrieval per ADR-006: one SQL statement recalls ~200 candidates by
embedding similarity with the hard filters applied in the same statement, then
the six-dimension scorer ranks those 200 only. Latency is therefore bounded by
the rerank-set size rather than by the corpus, which is what makes NFR-2's
"10,000 jobs under 500 ms" a property of the design instead of a hope.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    ApplicationRepositoryDep,
    CurrentUser,
    DbSession,
    EmbeddingProviderDep,
    JobServiceDep,
    MatchingServiceDep,
    RecommendationFeedbackRepositoryDep,
    ResumeVersionRepositoryDep,
)
from app.api.v1.jobs import summary_of
from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_logger
from app.schemas.application import ApplicationRead
from app.schemas.common import ErrorResponse
from app.schemas.match import MatchDimension, MatchedSkill, MatchSkills
from app.schemas.recommendation import (
    FeedbackRequest,
    RecommendationsResponse,
    RecommendedJob,
)
from app.services.matching.recall import recall_jobs
from app.services.matching.recommend import rank_jobs
from app.services.matching.weights import RANKING_VERSION

log = get_logger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get(
    "",
    response_model=RecommendationsResponse,
    summary="Jobs ranked for this caller",
    responses={404: {"model": ErrorResponse, "description": "No such resume version"}},
)
async def list_recommendations(
    user: CurrentUser,
    session: DbSession,
    matching: MatchingServiceDep,
    jobs_service: JobServiceDep,
    applications: ApplicationRepositoryDep,
    resume_versions: ResumeVersionRepositoryDep,
    provider: EmbeddingProviderDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    min_score: Annotated[Decimal | None, Query(ge=0, le=100)] = None,
    exclude_applied: Annotated[bool, Query()] = True,
    resume_version_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RecommendationsResponse:
    """Ranked jobs, cursor paginated.

    **Synchronous on every request**, which resolves api.md's open question about
    whether a cache miss should return `202` and stream instead. The cold case
    that question worried about is "no embeddings yet", and that is not a slow
    response — it is `PENDING`, answered immediately. A `202` would make the
    common warm path pay for a rare cold one, and would put a polling loop in
    the client for a request that already returns in the time a page takes to
    paint.

    Always 200. `availability` carries the three ways `items` can be empty.
    """
    if resume_version_id is not None:
        # 404 rather than 403 for someone else's resume: a 403 would confirm the
        # id exists, which is a membership oracle over other people's uploads.
        # Same rule as GET /jobs/{id}/match, which this mirrors deliberately.
        if await resume_versions.get_owned(resume_version_id, user.id) is None:
            raise ResourceNotFoundError("Resume version")
        chosen = resume_version_id
    else:
        chosen = await matching.default_resume_version_id(user.id)

    if chosen is None:
        return RecommendationsResponse(availability="NO_RESUME", limit=limit)

    if provider is None:
        # No provider means no vectors to compare, which is indistinguishable
        # from an unindexed resume as far as this endpoint can act on it.
        return RecommendationsResponse(
            availability="PENDING", limit=limit, resume_version_id=chosen
        )

    recalled = await recall_jobs(
        session=session,
        user_id=user.id,
        resume_version_id=chosen,
        model_name=provider.model_name,
        exclude_applied=exclude_applied,
    )
    if recalled is None:
        return RecommendationsResponse(
            availability="PENDING", limit=limit, resume_version_id=chosen
        )

    ids = [row.job_id for row in recalled]
    # Stage one already computed these, ordering its own result by them. Carrying
    # them forward is what keeps stage two from asking the database 200 more
    # times for numbers it was handed.
    cosines = {row.job_id: Decimal(str(row.similarity)) for row in recalled}
    by_id = {job.id: job for job in await jobs_service.get_many(ids)}
    # Ordered by the recall query, not by the dict — a mapping would lose the
    # ordering, and although stage two re-sorts anyway, a lost row would be
    # silent.
    ordered = [by_id[job_id] for job_id in ids if job_id in by_id]

    page = await rank_jobs(
        service=matching,
        user_id=user.id,
        resume_version_id=chosen,
        jobs=ordered,
        cosines=cosines,
        limit=limit,
        cursor=cursor,
        min_score=min_score,
    )

    page_ids = [result.job_id for result in page.items]
    live = await applications.for_jobs(user_id=user.id, job_ids=page_ids)

    items = [
        RecommendedJob(
            job=summary_of(
                by_id[result.job_id],
                application=(
                    ApplicationRead.model_validate(live[result.job_id])
                    if result.job_id in live
                    else None
                ),
            ),
            score=result.overall_score,
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
                matched=[_skill(s) for s in result.skills.matched],
                partial=[_skill(s) for s in result.skills.partial],
                missing=[_skill(s) for s in result.skills.missing],
            ),
        )
        for result in page.items
    ]

    return RecommendationsResponse(
        items=items,
        availability="READY",
        next_cursor=page.next_cursor,
        limit=limit,
        considered=len(ordered),
        ranking_version=page.items[0].ranking_version if page.items else None,
        resume_version_id=chosen,
        computed_at=page.items[0].computed_at if page.items else None,
    )


def _skill(skill) -> MatchedSkill:  # type: ignore[no-untyped-def]
    return MatchedSkill(id=skill.skill_id, name=skill.name, requirement=skill.requirement)


@router.post(
    "/{job_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Say whether a recommendation was any good",
    responses={404: {"model": ErrorResponse, "description": "No such job"}},
)
async def submit_feedback(
    job_id: uuid.UUID,
    payload: FeedbackRequest,
    user: CurrentUser,
    jobs_service: JobServiceDep,
    feedback: RecommendationFeedbackRepositoryDep,
) -> None:
    """Record a relevance judgement (ADR-005).

    **Nothing reads these rows yet**, and the endpoint ships anyway. A learned
    ranker needs labelled relevance data, and that can only be gathered forward
    in time — adding this in Phase 9 would mean starting against an empty table
    however good the model is by then.

    `204`, not `200` with a body: there is nothing useful to return, and an echo
    of what was just sent invites a client to re-render from it.

    Idempotent. Sending a second opinion replaces the first rather than
    appending, because a record of somebody changing their mind is not a
    training label — and two taps in quick succession on a phone must not become
    a unique-constraint error the user did nothing to deserve.
    """
    # 404 for an unknown job before anything is written, so feedback cannot
    # accumulate against ids that were never real.
    await jobs_service.get_job(job_id)

    await feedback.record(
        user_id=user.id,
        job_id=job_id,
        rating=payload.rating,
        # Which ranker they were reacting to. Without it the label is
        # uninterpretable later: "this was a bad recommendation" says nothing
        # unless you know what made it.
        ranking_version=RANKING_VERSION,
    )
