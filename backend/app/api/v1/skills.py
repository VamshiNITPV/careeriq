"""Skill taxonomy search and candidate skill management (api.md section 2.6)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import (
    CandidateSkillRepositoryDep,
    CurrentUser,
    DbSession,
    ProfileServiceDep,
    ResumeVersionRepositoryDep,
    SkillRepositoryDep,
)
from app.core.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.ids import uuid7
from app.data.skill_taxonomy import normalize_skill_text
from app.models.skill import CandidateSkill, Skill
from app.schemas.common import ErrorResponse, MessageResponse
from app.schemas.resume import (
    CandidateSkillCreate,
    CandidateSkillRead,
    CandidateSkillUpdate,
    SkillRead,
)
from app.schemas.skill_gap import SkillGapRead, SkillGapsResponse
from app.services.skill.gaps import compute_gaps

skills_router = APIRouter(prefix="/skills", tags=["skills"])
profile_skills_router = APIRouter(prefix="/profile/skills", tags=["profile"])


@skills_router.get(
    "/search",
    response_model=list[SkillRead],
    summary="Search the skill taxonomy",
)
async def search_skills(
    skills: SkillRepositoryDep,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Search term")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[SkillRead]:
    """Alias-aware autocomplete.

    Searching aliases as well as names is the point: typing "postgres" must find
    PostgreSQL, or the taxonomy's alias resolution is invisible to the user
    adding a skill by hand.
    """
    results = await skills.search(q, limit=limit)
    return [SkillRead.model_validate(s) for s in results]


@profile_skills_router.get(
    "",
    response_model=list[CandidateSkillRead],
    summary="Your skills",
)
async def list_my_skills(
    user: CurrentUser, candidate_skills: CandidateSkillRepositoryDep
) -> list[CandidateSkillRead]:
    rows = await candidate_skills.list_for_user(user.id)
    return [CandidateSkillRead.model_validate(row) for row in rows]


@profile_skills_router.post(
    "",
    response_model=CandidateSkillRead,
    status_code=201,
    summary="Add a skill manually",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown skill"},
        409: {"model": ErrorResponse, "description": "Already on your profile"},
    },
)
async def add_skill(
    payload: CandidateSkillCreate,
    user: CurrentUser,
    skills: SkillRepositoryDep,
    candidate_skills: CandidateSkillRepositoryDep,
    versions: ResumeVersionRepositoryDep,
) -> CandidateSkillRead:
    """Add a skill to your profile, by id or by name.

    A name that is not in the taxonomy creates a new entry marked unverified.
    No taxonomy is ever complete, and refusing a skill because we have not
    heard of it leaves the user with no way to record something true about
    themselves. Unverified entries are visible to admins for curation and do
    not pollute anything that relies on the verified set.
    """
    if payload.skill_id is not None:
        skill = await skills.get(payload.skill_id)
        if skill is None:
            raise ResourceNotFoundError("Skill")
    else:
        assert payload.skill_name is not None  # guaranteed by the schema validator
        normalized = normalize_skill_text(payload.skill_name)
        if not normalized:
            raise ValidationError("That skill name is not usable.")

        # Resolve against existing entries first, aliases included: typing
        # "postgres" must attach to PostgreSQL rather than create a duplicate
        # skill that nothing else in the system will ever match.
        existing = await skills.search(normalized, limit=1)
        skill = next(
            (s for s in existing if s.normalized_name == normalized or normalized in s.aliases),
            None,
        )

        if skill is None:
            skill = Skill(
                id=uuid7(),
                name=payload.skill_name.strip()[:120],
                normalized_name=normalized,
                aliases=[],
                # Created from user input, so it has not been reviewed. Phase 5
                # curates these against the job corpus.
                is_verified=False,
            )
            skills.add(skill)
            await skills.flush()

    existing_row = await candidate_skills.get_for_skill(user.id, skill.id)
    if existing_row is not None:
        if not existing_row.is_rejected:
            raise DuplicateResourceError("That skill is already on your profile.")
        # Adding back something previously removed. The tombstone is the only
        # thing standing in the way, and clearing it here is the only way it
        # clears — asking the user to remove a skill they cannot see would be
        # the obvious dead end.
        existing_row.is_rejected = False
        existing_row.is_user_verified = True
        # Provenance is dropped: the user typed this in, so it is no longer
        # derived from any resume and must not be swept away when one is
        # deleted. `delete_for_resume` keys on `source_version_id` precisely so
        # hand-added skills survive.
        existing_row.source_version_id = None
        await candidate_skills.flush()
        return CandidateSkillRead.model_validate(existing_row)

    # Ownership is checked before the id is trusted: an unchecked version id
    # would let a caller attach their skill to somebody else's resume.
    source_version_id: uuid.UUID | None = None
    if payload.source_version_id is not None:
        version = await versions.get_owned(payload.source_version_id, user.id)
        if version is None:
            raise ResourceNotFoundError("Resume version")
        source_version_id = version.id

    row = CandidateSkill(
        id=uuid7(),
        user_id=user.id,
        skill_id=skill.id,
        proficiency=payload.proficiency,
        years_of_experience=payload.years_of_experience,
        last_used_year=payload.last_used_year,
        source_version_id=source_version_id,
        # A skill the user added by hand is verified by definition, which also
        # protects it from being overwritten by a later re-parse (US-2.4 AC2).
        is_user_verified=True,
    )
    candidate_skills.add(row)
    await candidate_skills.flush()
    return CandidateSkillRead.model_validate(row)


@profile_skills_router.patch(
    "/{candidate_skill_id}",
    response_model=CandidateSkillRead,
    summary="Correct an extracted skill",
    responses={404: {"model": ErrorResponse}},
)
async def update_skill(
    candidate_skill_id: uuid.UUID,
    payload: CandidateSkillUpdate,
    user: CurrentUser,
    candidate_skills: CandidateSkillRepositoryDep,
) -> CandidateSkillRead:
    """Edit proficiency or experience on one of your skills (US-2.4).

    Any edit marks the row user-verified, which is what stops a subsequent
    re-parse of the resume from silently reverting the correction.
    """
    row = await candidate_skills.get_owned(candidate_skill_id, user.id)
    if row is None:
        raise ResourceNotFoundError("Skill")

    if payload.proficiency is not None:
        row.proficiency = payload.proficiency
    if payload.years_of_experience is not None:
        row.years_of_experience = payload.years_of_experience
    if payload.last_used_year is not None:
        row.last_used_year = payload.last_used_year

    row.is_user_verified = True
    await candidate_skills.flush()
    return CandidateSkillRead.model_validate(row)


@profile_skills_router.delete(
    "/{candidate_skill_id}",
    response_model=MessageResponse,
    summary="Remove a skill",
    responses={404: {"model": ErrorResponse}},
)
async def delete_skill(
    candidate_skill_id: uuid.UUID,
    user: CurrentUser,
    candidate_skills: CandidateSkillRepositoryDep,
) -> MessageResponse:
    row = await candidate_skills.get_owned(candidate_skill_id, user.id)
    if row is None:
        raise ResourceNotFoundError("Skill")

    # Marked, not deleted. A deleted row cannot survive the next parse of the
    # same resume, so the skill reappeared — reported once, then reproduced by a
    # re-extraction on 2026-09-12. The tombstone is what makes the removal stick.
    await candidate_skills.reject(row)
    return MessageResponse(message="Skill removed.")


@skills_router.get(
    "/gaps",
    response_model=SkillGapsResponse,
    summary="What you are missing, against your target roles or one job",
)
async def skill_gaps(
    user: CurrentUser,
    session: DbSession,
    profiles: ProfileServiceDep,
    job_id: Annotated[uuid.UUID | None, Query(description="Gaps against this job alone.")] = None,
) -> SkillGapsResponse:
    """Skills the target asks for, and whether the caller has them (US-5.1).

    **Computed per request, never stored.** `database.md` specifies a
    `skill_gaps` table; it is not built, for the reason ADR-006 gives for not
    caching match scores — a gap depends on the user's skills and on a corpus
    that changes daily, so a stored row would be wrong more often than right.

    Always 200. `availability` carries the two ways `items` can be empty that are
    not "you have no gaps": **NO_TARGET** when no target roles are set, and
    **NO_JOBS** when roles are set but no live posting matches them. Collapsing
    those into an empty list would congratulate someone on a completeness they
    have not been measured for — the same mistake the recommendations endpoint
    avoids with its own `availability`.
    """
    profile = await profiles.ensure(user.id)
    report = await compute_gaps(
        session,
        user_id=user.id,
        target_roles=list(profile.target_roles or []),
        job_id=job_id,
    )

    if job_id is None and not report.target_roles:
        availability = "NO_TARGET"
    elif report.target_jobs == 0:
        availability = "NO_JOBS"
    else:
        availability = "READY"

    return SkillGapsResponse(
        items=[
            SkillGapRead(
                skill_id=gap.skill_id,
                name=gap.name,
                category=gap.category,
                status=gap.status,
                severity=gap.severity,
                frequency=gap.frequency,
                job_count=gap.job_count,
            )
            for gap in report.gaps
        ],
        target_jobs=report.target_jobs,
        target_roles=report.target_roles,
        job_id=report.job_id,
        availability=availability,
    )
