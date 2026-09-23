"""What an interview for a role should examine (US-8.1 AC1).

Topics come from **what postings for the role actually demand**, not from a list
somebody typed. The same aggregation `services/skill/gaps.py` performs: find the
live postings whose title names the role, then group their `job_skills` weighted
by how firmly each is asked for.

So rehearsing for "AI Engineer" is examined on what AI Engineer adverts in this
corpus require. That is the difference between a mock interview and a quiz, and
it is most of what AC1 means by "generated from the target role" rather than
from a fixed bank.

## Why the topics are skills rather than themes

A theme ("System design") is something a model can wander around. A skill
("Distributed training", "PostgreSQL") is a thing the market named, and a
question about it can be checked against the posting that asked for it. It also
makes the interview's coverage comparable to the skill-gap screen, which reads
the same demand — the gap you were told to close is the gap you get asked about.

## When there is not enough to say

Two cases, and neither is an error:

- **No posting matches the role.** Somebody rehearsing for a job this corpus has
  never carried.
- **Too few match to mean anything.** A "blueprint" derived from two adverts is
  one employer's opinion, not market demand.

Both fall back to `policy.GENERIC_TOPICS`, and **the caller is told which it
got**. Presenting a two-advert sample as market-derived is the quiet overreach
the skill-gap screen already refuses by answering NO_JOBS instead of inventing a
number.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus, SkillRequirement
from app.models.job import Job, JobSkill
from app.models.skill import Skill
from app.services.interview.policy import GENERIC_TOPICS
from app.services.matching.weights import SKILL_REQUIREMENT_WEIGHT

#: How many matching postings before demand is worth calling demand.
#:
#: Three, which is low and deliberately so. The honest floor is higher -- the
#: skill-gap screen's own note says a rate over a handful of postings is one
#: employer's opinion -- but an interview that refuses to personalise until the
#: corpus is large is useless on a corpus that starts empty. Three is the point
#: where a topic appearing twice is no longer a coincidence, and the caller
#: always learns which source it got.
MIN_POSTINGS = 3

#: How many topics to examine. The budget is usually 10 questions and the policy
#: revisits topics when a candidate struggles, so more than this is never
#: reached and only dilutes the ordering.
MAX_TOPICS = 8


@dataclass(frozen=True, slots=True)
class Blueprint:
    """The topics to examine, and where they came from."""

    topics: tuple[str, ...]
    #: True when `topics` is the generic fallback rather than market demand.
    #:
    #: Carried rather than inferred from the value, because the two lists can
    #: coincide and a caller must never have to guess. It reaches the API so a
    #: user is not shown "based on what employers want" over a generic list.
    is_generic: bool
    #: How many live postings the demand was read from. Zero when generic.
    postings: int


async def blueprint_for(session: AsyncSession, *, role: str) -> Blueprint:
    """Topics for this role, from demand where there is enough of it."""
    cleaned = role.strip()
    if not cleaned:
        return Blueprint(topics=GENERIC_TOPICS, is_generic=True, postings=0)

    # Title matching, the same as `skill/gaps.py` and for the reason it states:
    # "your title says Data Engineer" is an explanation a reader can check,
    # where "the embedding thought it was close" is not.
    job_ids = list(
        (
            await session.scalars(
                select(Job.id).where(
                    Job.status == JobStatus.ACTIVE,
                    or_(Job.expires_at.is_(None), Job.expires_at > func.now()),
                    Job.title.ilike(f"%{cleaned}%"),
                )
            )
        ).all()
    )

    if len(job_ids) < MIN_POSTINGS:
        return Blueprint(topics=GENERIC_TOPICS, is_generic=True, postings=len(job_ids))

    # Weighted by how firmly each posting asks, so something four adverts
    # *require* outranks something six merely prefer. Same weights the match
    # score uses, so "what you are examined on" and "what you are scored on"
    # cannot drift apart.
    weight = func.sum(
        case(
            (
                JobSkill.requirement == SkillRequirement.REQUIRED,
                float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.REQUIRED]),
            ),
            else_=float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.PREFERRED]),
        )
    )
    rows = (
        await session.execute(
            select(Skill.name, weight.label("weighted"))
            .select_from(JobSkill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id.in_(job_ids))
            .group_by(Skill.id, Skill.name)
            # Name breaks ties, so two equally demanded skills order the same
            # way on every call -- an interview whose topic order shifted
            # between resumes would be a different interview each time.
            .order_by(weight.desc(), Skill.name)
            .limit(MAX_TOPICS)
        )
    ).all()

    if not rows:
        # Postings exist but none carry parsed skills. Real on a corpus whose
        # extraction has not run, and not something to present as demand.
        return Blueprint(topics=GENERIC_TOPICS, is_generic=True, postings=len(job_ids))

    return Blueprint(
        topics=tuple(row.name for row in rows),
        is_generic=False,
        postings=len(job_ids),
    )
