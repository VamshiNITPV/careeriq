"""What an interview should examine (US-8.1 AC1).

Topics come from **what is actually asked for**, not from a list somebody typed,
and there are two sources of that with a clear order of preference.

**The posting being targeted, where there is one.** Its own `job_skills`,
weighted by how firmly it asks. This is the only source that can honestly be
described as questions built for this job, and it is what a candidate with an
interview on Thursday wants.

**Otherwise, what the role generally demands** -- the same aggregation
`services/skill/gaps.py` performs: find the live postings whose title names the
role, then group their `job_skills` by firmness. Useful before you have found a
job to target, and it is a different claim, so it is reported as a different
claim.

## Why the topics are skills rather than themes

A theme ("System design") is something a model can wander around. A skill
("Distributed training", "PostgreSQL") is a thing someone named, and a question
about it can be checked against the posting that asked for it. It also makes the
interview's coverage comparable to the skill-gap screen, which reads the same
demand -- the gap you were told to close is the gap you get asked about.

## When there is not enough to say

Three cases, and none is an error:

- **The targeted posting parsed into too few skills.** Real on a posting that is
  mostly prose, or one whose vocabulary is outside the taxonomy. Falls through to
  the role aggregate rather than stretching two topics over ten questions.
- **No posting matches the role.** Somebody rehearsing for a job this corpus has
  never carried.
- **Too few match to mean anything.** A "blueprint" derived from two adverts is
  one employer's opinion, not market demand.

The last two fall back to `policy.GENERIC_TOPICS`, and **the caller is told which
of the three it got** -- `InterviewTopicSource`, carried on the result and stored
on the interview row. Presenting a two-advert sample as market-derived is the
quiet overreach the skill-gap screen already refuses by answering NO_JOBS instead
of inventing a number.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import InterviewTopicSource, JobStatus, SkillRequirement
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

#: How many skills one targeted posting must yield before it is used alone.
#:
#: The same shape of argument as `MIN_POSTINGS` over a different denominator. A
#: posting that parsed into one or two skills cannot fill a ten-question
#: interview, and the policy revisits a topic when a candidate struggles -- so
#: two topics across ten questions is five questions about each, which stops
#: being an interview and becomes an interrogation about one thing.
#:
#: Falling through to the role aggregate is the better failure: it is still real
#: demand for the role they are interviewing for, and the source says so.
MIN_JOB_TOPICS = 3

#: How many topics to examine. The budget is usually 10 questions and the policy
#: revisits topics when a candidate struggles, so more than this is never
#: reached and only dilutes the ordering.
MAX_TOPICS = 8


@dataclass(frozen=True, slots=True)
class Blueprint:
    """The topics to examine, and where they came from."""

    topics: tuple[str, ...]
    #: Which of the three sources produced `topics`.
    #:
    #: Carried rather than inferred from the value, because the lists can
    #: coincide and a caller must never have to guess. It reaches the API and the
    #: interview row, so a user is not shown "based on what this employer asks
    #: for" over a generic list.
    source: InterviewTopicSource
    #: How many live postings the demand was read from. One when the source is
    #: the targeted posting; zero when generic and nothing matched.
    postings: int


async def _weighted_topics(session: AsyncSession, job_ids: Sequence[uuid.UUID]) -> list[str]:
    """The most firmly demanded skills across these postings, best first.

    One helper for both sources, because it is the same aggregation over a
    different set of ids and two copies is how the two drift apart. Weighted by
    how firmly each posting asks, so something four adverts *require* outranks
    something six merely prefer -- and with the same weights the match score
    uses, so "what you are examined on" and "what you are scored on" cannot
    disagree.
    """
    if not job_ids:
        return []

    weight = func.sum(
        case(
            (
                JobSkill.requirement == SkillRequirement.REQUIRED,
                float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.REQUIRED]),
            ),
            else_=float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.PREFERRED]),
        )
    )
    # How clearly the posting asked, summed the same way.
    #
    # This is load-bearing for a single posting and nearly inert for a corpus,
    # which is exactly backwards from how it looks. Across 48 adverts the weight
    # above already separates everything. Within *one*, every REQUIRED skill
    # carries an identical weight -- and `job/skills.py` marks REQUIRED for the
    # Requirements section, the Responsibilities section and any unrecognised
    # one, so a real posting routinely has thirty of them and the sort collapses
    # to alphabetical.
    #
    # Found by running it: the first live comparison returned "Agile, CI/CD, Data
    # Processing, Docker, ETL, Embeddings, FastAPI, Flask" for an AI Engineer
    # posting whose text names Large Language Models, RAG and Python. `MAX_TOPICS`
    # had cut the substance off at the letter F. Confidence is the parser's own
    # answer to "how sure are we this was asked for" -- 0.99 from a Requirements
    # heading, 0.60 from a section it could not identify -- so it orders by
    # something this posting actually said, and keeps the provenance unmixed.
    confidence = func.sum(func.coalesce(JobSkill.extraction_confidence, 0))
    rows = (
        await session.execute(
            select(Skill.name, weight.label("weighted"))
            .select_from(JobSkill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id.in_(job_ids))
            .group_by(Skill.id, Skill.name)
            # Name last, so two skills equal on both measures order the same way
            # on every call -- an interview whose topic order shifted between
            # resumes would be a different interview each time.
            .order_by(weight.desc(), confidence.desc(), Skill.name)
            .limit(MAX_TOPICS)
        )
    ).all()
    return [row.name for row in rows]


async def blueprint_for(
    session: AsyncSession, *, role: str, job_id: uuid.UUID | None = None
) -> Blueprint:
    """Topics for this interview, from the targeted posting where there is one.

    `job_id` first and the role second, deliberately. A candidate who named the
    job they are interviewing for has told us the most specific thing they can,
    and averaging it into every other posting with a similar title throws that
    away -- which is what this function did before it took a job at all, so
    picking a job changed the prompt's background reading and not one topic.
    """
    if job_id is not None:
        # By id, with none of the ACTIVE / non-expired filtering the role branch
        # applies below. That filter exists to stop a *sample of market demand*
        # being drawn from dead adverts; a posting somebody applied to six weeks
        # ago is expired and is still exactly the thing they are interviewing
        # for. The route has already confirmed the row exists.
        #
        # `canonical_job_id` is deliberately not followed either: a duplicate
        # *submission* writes no row at all, so a job marked DUPLICATE has its
        # own `job_skills`, and chasing the pointer would examine a posting the
        # candidate never chose.
        from_job = await _weighted_topics(session, [job_id])
        if len(from_job) >= MIN_JOB_TOPICS:
            return Blueprint(
                topics=tuple(from_job),
                source=InterviewTopicSource.THIS_JOB,
                postings=1,
            )
        # Too thin to examine on its own. Falls through rather than failing --
        # the role's demand is still demand for the job they are interviewing
        # for, and the source records that this is what happened.

    cleaned = role.strip()
    if not cleaned:
        return Blueprint(
            topics=GENERIC_TOPICS, source=InterviewTopicSource.GENERIC, postings=0
        )

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
        return Blueprint(
            topics=GENERIC_TOPICS,
            source=InterviewTopicSource.GENERIC,
            postings=len(job_ids),
        )

    from_role = await _weighted_topics(session, job_ids)
    if not from_role:
        # Postings exist but none carry parsed skills. Real on a corpus whose
        # extraction has not run, and not something to present as demand.
        return Blueprint(
            topics=GENERIC_TOPICS,
            source=InterviewTopicSource.GENERIC,
            postings=len(job_ids),
        )

    return Blueprint(
        topics=tuple(from_role),
        source=InterviewTopicSource.ROLE_DEMAND,
        postings=len(job_ids),
    )
