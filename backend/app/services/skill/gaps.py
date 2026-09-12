"""Skill gaps against a target — one job, or the roles a user is aiming at (US-5.1).

Answers "what am I missing, and which of it matters most", which is the first
thing the matching work makes possible to say. A match score tells someone a job
is a 68; this tells them why, and what to do about it.

## Computed per request, not stored

`database.md` section 3.7 specifies a `skill_gaps` table. It is **not built**,
for the reason ADR-006 gives for not caching match scores: a gap depends on the
user's skills, which change the moment they edit their profile, and on the job
corpus, which changes daily. A stored row would be wrong more often than right,
and a cache that goes quietly stale is worse than no cache. The computation is
two indexed queries over a bounded set; it does not need saving.

That also leaves `database.md`'s open question — whether gaps need history —
genuinely open rather than answered by accident. History is a different feature
("gaps closed over time") and would need a table designed for it.

## Severity

US-5.1 AC2: *"Missing skills are prioritized critical | high | medium | low based
on how often they appear as **required** across my target roles."*

`database.md` sketches severity as `demand_score * requirement weight` instead.
Those are different things and the AC wins: `demand_score` is the fraction of
**every** active posting wanting a skill, which says how common it is in the
market, not how much it matters to the person asking. Someone targeting ML roles
does not need to know that 45% of all jobs mention communication.

So frequency is measured **within the target set**, weighted by how the posting
asks for it — `SKILL_REQUIREMENT_WEIGHT`, the same 1.0 / 0.5 the ranking formula
uses, because "required" and "nice to have" should not mean two different things
in two places.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus, SkillRequirement
from app.models.job import Job, JobSkill
from app.models.skill import CandidateSkill, Skill
from app.services.matching.weights import SKILL_REQUIREMENT_WEIGHT


class GapStatus(StrEnum):
    """What the user has, against what the target asks for."""

    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


class GapSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


#: Weighted frequency at which a missing skill becomes each severity.
#:
#: Read as "what share of the jobs I am aiming at ask for this". Judgement, not
#: measurement — there is no labelled set of "correctly prioritised gaps" to fit
#: against, and inventing one by fitting these to the current corpus would make
#: them describe today's job market rather than the user's target.
#:
#: Kept as one named table rather than a chain of literals so the choice is
#: visible and arguable, and so changing it is one edit.
_SEVERITY_BANDS: tuple[tuple[Decimal, GapSeverity], ...] = (
    (Decimal("0.60"), GapSeverity.CRITICAL),
    (Decimal("0.35"), GapSeverity.HIGH),
    (Decimal("0.15"), GapSeverity.MEDIUM),
)

#: Below this share of target jobs, a skill is not reported as a gap at all.
#:
#: Without a floor the list is mostly noise: across a few hundred postings almost
#: every taxonomy entry appears once somewhere, and a gap list that includes
#: everything tells the reader nothing about what to do next.
_MIN_FREQUENCY = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class SkillGap:
    skill_id: uuid.UUID
    name: str
    category: str
    status: GapStatus
    severity: GapSeverity
    #: Weighted share of target jobs asking for this, in [0, 1].
    frequency: Decimal
    #: How many target jobs mention it at all, for a reader who wants the count
    #: rather than the fraction.
    job_count: int


@dataclass(frozen=True, slots=True)
class GapReport:
    """The answer, plus what it was computed against.

    `target_jobs` matters as much as the gaps: a report built from four postings
    is a different claim from one built from ninety, and hiding the denominator
    would let a reader over-read a small sample.
    """

    gaps: list[SkillGap]
    target_jobs: int
    target_roles: list[str]
    #: Set when the caller asked about one specific job instead of their roles.
    job_id: uuid.UUID | None


def _severity(frequency: Decimal) -> GapSeverity:
    for threshold, severity in _SEVERITY_BANDS:
        if frequency >= threshold:
            return severity
    return GapSeverity.LOW


async def _target_job_ids(
    session: AsyncSession, roles: list[str], *, limit: int = 500
) -> list[uuid.UUID]:
    """Live postings whose title names one of the user's target roles.

    Title matching rather than semantic similarity, deliberately. This feature
    tells someone what to go and learn, so "these are the jobs I looked at" has
    to be answerable — and "your title says Data Engineer" is an explanation a
    reader can check, while "the embedding thought it was close" is not.

    The cost is real and worth stating: a role written "Backend Engineer" will
    miss a posting titled "Software Engineer II, Platform". Semantic matching
    would catch it and is the obvious upgrade once there is any evidence the
    miss matters.
    """
    if not roles:
        return []

    patterns = [Job.title.ilike(f"%{role.strip()}%") for role in roles if role.strip()]
    if not patterns:
        return []

    stmt = (
        select(Job.id)
        .where(
            Job.status == JobStatus.ACTIVE,
            or_(Job.expires_at.is_(None), Job.expires_at > func.now()),
            or_(*patterns),
        )
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def compute_gaps(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    target_roles: list[str],
    job_id: uuid.UUID | None = None,
) -> GapReport:
    """Gaps against one job, or against every posting matching the target roles.

    One code path for both, because they are the same question over a different
    set of jobs. Two implementations would drift, and the single-job answer would
    eventually disagree with the aggregate that contains it.
    """
    if job_id is not None:
        job_ids = [job_id]
        roles: list[str] = []
    else:
        roles = [r for r in target_roles if r.strip()]
        job_ids = await _target_job_ids(session, roles)

    if not job_ids:
        return GapReport(gaps=[], target_jobs=0, target_roles=roles, job_id=job_id)

    # What the target jobs ask for, weighted by how firmly they ask. One row per
    # skill: the weighted sum, and how many postings mention it at all.
    weight = func.sum(
        case(
            (
                JobSkill.requirement == SkillRequirement.REQUIRED,
                float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.REQUIRED]),
            ),
            else_=float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.PREFERRED]),
        )
    )

    demand = (
        await session.execute(
            select(
                Skill.id,
                Skill.name,
                Skill.category,
                weight.label("weighted"),
                func.count().label("mentions"),
            )
            .select_from(JobSkill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id.in_(job_ids))
            .group_by(Skill.id, Skill.name, Skill.category)
        )
    ).all()

    held = {
        row[0]
        for row in (
            await session.execute(
                select(CandidateSkill.skill_id).where(
                    CandidateSkill.user_id == user_id,
                    CandidateSkill.is_rejected.is_(False),
                )
            )
        ).all()
    }

    # One level of the taxonomy tree, so a candidate's React counts as partial
    # credit against a job's JavaScript. The same rule the ranking's skill
    # dimension applies, and for the same reason: treating a related skill as a
    # total absence overstates the gap.
    related: set[uuid.UUID] = set()
    if held:
        related = {
            row[0]
            for row in (
                await session.execute(
                    select(Skill.id).where(
                        or_(
                            Skill.parent_skill_id.in_(held),
                            Skill.id.in_(
                                select(Skill.parent_skill_id).where(
                                    Skill.id.in_(held), Skill.parent_skill_id.is_not(None)
                                )
                            ),
                        )
                    )
                )
            ).all()
        }

    total = Decimal(len(job_ids))
    gaps: list[SkillGap] = []

    for skill_id, name, category, weighted, mentions in demand:
        frequency = (Decimal(str(weighted or 0)) / total).quantize(Decimal("0.0001"))
        if frequency < _MIN_FREQUENCY:
            continue

        if skill_id in held:
            status = GapStatus.STRONG
        elif skill_id in related:
            status = GapStatus.PARTIAL
        else:
            status = GapStatus.MISSING

        gaps.append(
            SkillGap(
                skill_id=skill_id,
                name=name,
                category=category,
                status=status,
                severity=_severity(frequency),
                frequency=frequency,
                job_count=int(mentions),
            )
        )

    # Missing first, then by how much the target set wants it. A reader scanning
    # this wants the next thing to learn at the top, not an alphabet.
    order = {GapStatus.MISSING: 0, GapStatus.PARTIAL: 1, GapStatus.STRONG: 2}
    gaps.sort(key=lambda g: (order[g.status], -g.frequency, g.name))

    return GapReport(
        gaps=gaps,
        target_jobs=len(job_ids),
        target_roles=roles,
        job_id=job_id,
    )
