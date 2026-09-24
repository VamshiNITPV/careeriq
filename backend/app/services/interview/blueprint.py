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

## And within either source, the gap comes first

Demand says what the job wants. It says nothing about whether this candidate can
already do it, so a list built from demand alone examines six years of somebody's
experience as readily as something they have never touched. The questions worth
rehearsing are the ones you would actually struggle with.

So each skill's weight is multiplied by whether the candidate holds it --
`skill/gaps.py`'s own answer, reused rather than recomputed, because the gap a
user was told to close should be the gap they get asked about. A preference and
not a filter: a REQUIRED skill they lack outranks a REQUIRED skill they have, and
a PREFERRED skill they lack still ranks below it. An interview that was only your
weakest subjects would be neither realistic nor much use -- rehearsing the
answers you are good at is part of the point.

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
from app.services.skill.gaps import held_and_related

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

#: How much a skill the candidate does not have outranks one they do.
#:
#: The questions worth rehearsing are the ones you would actually struggle with,
#: and the skill-gap screen already computes exactly which those are. Without
#: this, the topics were the job's demand in the abstract -- they could as easily
#: be things the candidate has done for six years as things they have never
#: touched, and nothing preferred one.
#:
#: **Multiplicative, not additive, and that is not a detail.** A flat bonus large
#: enough to matter against one posting's weight of 1.0 is invisible against a
#: sum over forty-eight, so the same constant would change everything on the
#: targeted path and nothing on the aggregate one.
#:
#: **A preference, not a filter**, and the size is what keeps it one. At 1.4, a
#: REQUIRED skill they lack (1.4) outranks a REQUIRED skill they have (1.0), and a
#: PREFERRED skill they lack (0.7) still ranks *below* a REQUIRED skill they have
#: (1.0) -- so the job's own emphasis stays primary and an interview does not
#: become an hour on your weakest subject. It should not: a real interview asks
#: about your strengths too, and rehearsing the answers you are good at is part
#: of the point.
MISSING_MULTIPLIER = 1.4

#: Half the lift, for a skill one taxonomy level from something they hold.
#:
#: Their React against the job's JavaScript is neither a gap nor a strength, and
#: `skill/gaps.py` calls it PARTIAL for the same reason. Worth probing above a
#: skill they plainly have, below one they plainly lack.
PARTIAL_MULTIPLIER = 1.2


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


async def _weighted_topics(
    session: AsyncSession,
    job_ids: Sequence[uuid.UUID],
    *,
    held: frozenset[uuid.UUID] = frozenset(),
    related: frozenset[uuid.UUID] = frozenset(),
) -> list[str]:
    """The skills most worth examining across these postings, best first.

    One helper for both sources, because it is the same aggregation over a
    different set of ids and two copies is how the two drift apart. Weighted by
    how firmly each posting asks, with the same weights the match score uses, so
    "what you are examined on" and "what you are scored on" cannot disagree.

    `held` and `related` lift what the candidate cannot yet do. They come from
    `skill/gaps.py`, which is the point: the gap a user was told to close is then
    the gap they get asked about, rather than two features disagreeing about what
    their weaknesses are.
    """
    if not job_ids:
        return []

    # Requirement first, then the gap. The product of the two is the ordering,
    # and the multipliers are sized so the job's own emphasis stays primary --
    # see MISSING_MULTIPLIER.
    firmness = case(
        (
            JobSkill.requirement == SkillRequirement.REQUIRED,
            float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.REQUIRED]),
        ),
        else_=float(SKILL_REQUIREMENT_WEIGHT[SkillRequirement.PREFERRED]),
    )
    # `held` is checked before `related`: a skill they actually have is a
    # strength even when it also happens to sit next to another one they have.
    gap = case(
        (JobSkill.skill_id.in_(held), 1.0),
        (JobSkill.skill_id.in_(related), PARTIAL_MULTIPLIER),
        else_=MISSING_MULTIPLIER,
    )
    weight = func.sum(firmness * gap)
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
    session: AsyncSession,
    *,
    role: str,
    job_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Blueprint:
    """Topics for this interview, from the targeted posting where there is one.

    `job_id` first and the role second, deliberately. A candidate who named the
    job they are interviewing for has told us the most specific thing they can,
    and averaging it into every other posting with a similar title throws that
    away -- which is what this function did before it took a job at all, so
    picking a job changed the prompt's background reading and not one topic.
    """
    # Resolved once, before either branch, so the fall-through from a thin
    # posting to role demand does not re-ask the same two questions. Optional,
    # because the function is used in tests and scripts without a user -- and
    # without one the ordering is simply the job's demand, which is what it was
    # before the gap existed.
    held: frozenset[uuid.UUID] = frozenset()
    related: frozenset[uuid.UUID] = frozenset()
    if user_id is not None:
        got, near = await held_and_related(session, user_id=user_id)
        held, related = frozenset(got), frozenset(near)

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
        from_job = await _weighted_topics(session, [job_id], held=held, related=related)
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

    from_role = await _weighted_topics(session, job_ids, held=held, related=related)
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
