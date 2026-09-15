"""Resume optimization (US-6.1, api.md section 2.7).

The most safety-critical surface in the API. Three things it does not do, each
on purpose:

* It never returns a suggestion that failed validation. Those are not stored, so
  there is nothing here to leak them; the count is reported instead, because a
  silent validator is indistinguishable from a model with nothing to say.
* It never mutates the source resume version. Accepting produces a new one.
* It never infers acceptance. A suggestion is applied because the user named its
  id, the same rule that governs marking a job applied.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import select

from app.api.deps import (
    AnalysisRunnerDep,
    CurrentUser,
    DbSession,
    ResumeVersionRepositoryDep,
    get_storage,
)
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.ids import uuid7
from app.integrations.storage import ObjectStorage
from app.models.enums import AnalysisStatus
from app.models.job import Job
from app.models.optimization import OptimizationAnalysis, OptimizationSuggestion
from app.schemas.common import ErrorResponse
from app.schemas.optimization import (
    AnalysisRead,
    AnalyzeRequest,
    AnalyzeResponse,
    ApplyResponse,
    DecideRequest,
    SuggestionRead,
)
from app.services.resume.apply_suggestions import NothingToApplyError, apply_accepted

router = APIRouter(prefix="/optimize", tags=["optimization"])


async def _owned_analysis(
    session: DbSession, analysis_id: uuid.UUID, user_id: uuid.UUID
) -> OptimizationAnalysis:
    """Fetch an analysis, or 404.

    A row belonging to someone else is reported as missing rather than
    forbidden, per US-1.5 AC1: a 403 confirms the id exists.
    """
    analysis = await session.get(OptimizationAnalysis, analysis_id)
    if analysis is None or analysis.user_id != user_id:
        raise ResourceNotFoundError("Analysis not found.")
    return analysis


@router.post(
    "/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tailor a resume version to a job",
    responses={404: {"model": ErrorResponse, "description": "Resume version or job not found"}},
)
async def analyze(
    payload: AnalyzeRequest,
    user: CurrentUser,
    session: DbSession,
    versions: ResumeVersionRepositoryDep,
    background: BackgroundTasks,
    run_analysis: AnalysisRunnerDep,
) -> AnalyzeResponse:
    """Start an analysis and answer immediately.

    202 because a model call takes seconds and holding the request open for it
    makes every client's timeout our problem. Ownership and existence are
    checked *here* rather than in the background, so a bad request fails with a
    precise status instead of being queued and failing where nobody is looking
    (the same reasoning as resume upload).
    """
    # `get_owned` rather than `get` plus an ownership check. The repository's own
    # docstring gives the reason -- a separate `if x.user_id != user_id` is one
    # forgotten line away from a cross-user read -- and the first version here
    # reached through `version.resume`, which is a lazy load that raises the
    # moment the instance was not loaded with its relationship.
    version = await versions.get_owned(payload.resume_version_id, user.id)
    if version is None:
        raise ResourceNotFoundError("Resume version not found.")

    job = await session.scalar(select(Job).where(Job.id == payload.job_id))
    if job is None:
        raise ResourceNotFoundError("Job not found.")

    analysis = OptimizationAnalysis(
        id=uuid7(),
        user_id=user.id,
        resume_version_id=version.id,
        job_id=job.id,
    )
    session.add(analysis)
    await session.commit()

    # Runs after the response is sent, and opens its own session because this
    # one closes with the request. Interim, like the resume pipeline: tasks die
    # with the process until the queue in Phase 10 (ADR-018).
    background.add_task(run_analysis, analysis.id)

    return AnalyzeResponse(
        analysis_id=analysis.id,
        status=analysis.status,
        poll_url=f"/api/v1/optimize/{analysis.id}",
    )


@router.get(
    "/{analysis_id}",
    summary="Suggestions from one analysis",
    responses={404: {"model": ErrorResponse, "description": "Analysis not found"}},
)
async def read_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AnalysisRead:
    analysis = await _owned_analysis(session, analysis_id, user.id)

    rows = await session.scalars(
        select(OptimizationSuggestion)
        .where(OptimizationSuggestion.analysis_id == analysis.id)
        .order_by(OptimizationSuggestion.position)
    )

    return AnalysisRead(
        analysis_id=analysis.id,
        resume_version_id=analysis.resume_version_id,
        job_id=analysis.job_id,
        status=analysis.status,
        error=analysis.error,
        suggestions=[
            SuggestionRead(
                id=row.id,
                position=row.position,
                section=row.section,
                original=row.original,
                suggested=row.suggested,
                rationale=row.rationale,
                grounded_in=list(row.grounded_in or []),
                decision=row.decision,
                decided_at=row.decided_at,
            )
            for row in rows
        ],
        rejected_by_validator=analysis.rejected_by_validator,
        dropped_malformed=analysis.dropped_malformed,
        completed_at=analysis.completed_at,
    )


@router.post(
    "/{analysis_id}/apply",
    status_code=status.HTTP_201_CREATED,
    summary="Apply accepted suggestions as a new resume version",
    responses={
        404: {"model": ErrorResponse, "description": "Analysis not found"},
        409: {"model": ErrorResponse, "description": "Analysis has not finished"},
        422: {"model": ErrorResponse, "description": "Nothing could be applied"},
    },
)
async def apply(
    analysis_id: uuid.UUID,
    payload: DecideRequest,
    user: CurrentUser,
    session: DbSession,
    versions: ResumeVersionRepositoryDep,
    storage: Annotated[ObjectStorage, Depends(get_storage)],
) -> ApplyResponse:
    """Create a **new** resume version from the accepted suggestions.

    The source version is never modified (US-6.1 AC3). Suggestions not named are
    marked rejected, so the analysis is fully decided and nothing re-offers text
    the user has already passed over.
    """
    analysis = await _owned_analysis(session, analysis_id, user.id)

    if analysis.status is not AnalysisStatus.COMPLETE:
        raise ValidationError("This analysis hasn't finished yet.")

    source = await versions.get(analysis.resume_version_id)
    if source is None:
        raise ResourceNotFoundError("The resume version this analysis ran against is gone.")

    accepted = set(payload.accepted_suggestion_ids)
    try:
        result = await apply_accepted(
            session,
            analysis=analysis,
            source=source,
            accepted_ids=accepted,
            storage=storage,
        )
    except NothingToApplyError as exc:
        # No rollback needed: `apply_accepted` decides in full before it writes
        # anything, so a failure here has left every row untouched. Undoing a
        # write that never happened is the kind of ceremony that looks careful
        # and hides whether the invariant actually holds.
        raise ValidationError(str(exc)) from exc

    await session.commit()

    note = f"Created version {result.version.version_number} with {result.applied} change"
    note += "" if result.applied == 1 else "s"
    if result.not_found:
        # Surfaced rather than swallowed: the user chose these, and a count that
        # quietly differs from what they picked is the kind of thing that
        # destroys trust in the feature.
        note += (
            f". {result.not_found} couldn't be applied because that wording is no longer "
            "in the resume."
        )

    return ApplyResponse(
        resume_version_id=result.version.id,
        version_number=result.version.version_number,
        applied=result.applied,
        rejected=result.rejected,
        message=note + ".",
    )
