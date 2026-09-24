"""What an interview examines, and where it says that came from (US-8.1 AC1).

There was no test for `blueprint_for` at all before this file, which is how its
docstring came to claim for a whole phase that `is_generic` "reaches the API" --
a sentence nothing enforced and nothing made true.

Database-backed but in `tests/unit/`, following `test_apply_suggestions.py` and
`test_optimization_service.py`: the function is a query, so a fake session would
test the mock. No model is involved anywhere here.

The assertion that matters most is `test_a_targeted_job_beats_the_role_aggregate`.
It is the entire claim of this change -- that picking a job changes what you are
asked about, which it did not do before.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.data.skill_taxonomy import normalize_skill_text
from app.models.enums import (
    InterviewTopicSource,
    JobSource,
    JobStatus,
    SkillRequirement,
)
from app.models.job import Job, JobSkill
from app.models.skill import Skill
from app.services.interview.blueprint import (
    MIN_JOB_TOPICS,
    MIN_POSTINGS,
    blueprint_for,
)
from app.services.interview.policy import GENERIC_TOPICS

ROLE = "Backend Engineer"


async def _skill(session: AsyncSession, name: str) -> Skill:
    # `normalized_name` is NOT NULL and there is one normaliser for it, the same
    # one `POST /skills` uses -- inventing a second here would let this file's
    # skills be matched differently from every other skill in the system.
    skill = Skill(
        id=uuid7(),
        name=name,
        normalized_name=normalize_skill_text(name),
        category="tool",
        aliases=[],
    )
    session.add(skill)
    await session.flush()
    return skill


async def _job(
    session: AsyncSession,
    *,
    title: str = ROLE,
    skills: Sequence[tuple[Skill, SkillRequirement]] = (),
    status: JobStatus = JobStatus.ACTIVE,
    expires_at: datetime | None = None,
    canonical_job_id: uuid.UUID | None = None,
) -> Job:
    """A job carrying exactly the skills this test is about.

    Built by hand rather than through the parser: these tests are about the
    aggregation and its thresholds, and a posting whose extracted skills depend
    on heuristics would make every assertion here about the heuristics instead.
    """
    job = Job(
        id=uuid7(),
        title=title,
        description_raw=f"A posting for a {title}. " * 20,
        content_hash=uuid.uuid4().hex,
        source=JobSource.USER_SUBMITTED,
        status=status,
        expires_at=expires_at,
        canonical_job_id=canonical_job_id,
    )
    for skill, requirement in skills:
        job.skills.append(JobSkill(skill_id=skill.id, requirement=requirement))
    session.add(job)
    await session.flush()
    return job


class TestATargetedJob:
    """The change this file exists for."""

    async def test_a_targeted_job_beats_the_role_aggregate(
        self, db_session: AsyncSession
    ) -> None:
        """Picking a job changes what you are examined on.

        Before this, `blueprint_for` took a role string only: the chosen job
        contributed its raw text to the prompt as background reading and not one
        topic. An interview "for this job" examined the corpus average.
        """
        kafka = await _skill(db_session, "Kafka")
        pg = await _skill(db_session, "PostgreSQL")
        redis = await _skill(db_session, "Redis")
        java = await _skill(db_session, "Java")

        target = await _job(
            db_session,
            skills=[
                (kafka, SkillRequirement.REQUIRED),
                (pg, SkillRequirement.REQUIRED),
                (redis, SkillRequirement.REQUIRED),
            ],
        )
        # Enough other postings for the role path to be available and to win if
        # the job were ignored -- Java appears in all of them and in none of the
        # target.
        for _ in range(MIN_POSTINGS):
            await _job(db_session, skills=[(java, SkillRequirement.REQUIRED)])

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.source is InterviewTopicSource.THIS_JOB
        assert blueprint.postings == 1
        assert set(blueprint.topics) == {"Kafka", "PostgreSQL", "Redis"}
        assert "Java" not in blueprint.topics

    async def test_required_outranks_preferred_within_one_posting(
        self, db_session: AsyncSession
    ) -> None:
        """The order is what the policy walks, so it is behaviour.

        Same weights the match score uses, so "what you are examined on" and
        "what you are scored on" cannot drift apart.
        """
        wanted = await _skill(db_session, "AAA Preferred")
        needed = await _skill(db_session, "ZZZ Required")
        extra = await _skill(db_session, "MMM Also Required")

        target = await _job(
            db_session,
            skills=[
                (wanted, SkillRequirement.PREFERRED),
                (needed, SkillRequirement.REQUIRED),
                (extra, SkillRequirement.REQUIRED),
            ],
        )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        # Both REQUIRED first, name breaking their tie; the PREFERRED one last
        # despite sorting first alphabetically.
        assert blueprint.topics == ("MMM Also Required", "ZZZ Required", "AAA Preferred")

    async def test_an_expired_posting_still_counts_when_it_was_chosen(
        self, db_session: AsyncSession
    ) -> None:
        """The ACTIVE filter belongs to the role path, not this one.

        It exists to stop a *sample of market demand* being drawn from dead
        adverts. A posting somebody applied to six weeks ago is closed and is
        still exactly the thing they are interviewing for.
        """
        skills = [
            (await _skill(db_session, f"Expired {n}"), SkillRequirement.REQUIRED)
            for n in range(MIN_JOB_TOPICS)
        ]
        # Expiry is a fact about `expires_at`, not a status: `JobStatus` has no
        # EXPIRED member and `models/enums.py:181` records why.
        target = await _job(
            db_session,
            skills=skills,
            expires_at=datetime.now(UTC) - timedelta(days=42),
        )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.source is InterviewTopicSource.THIS_JOB


class TestWhenTheTargetedJobIsTooThin:
    async def test_it_falls_through_to_the_role_aggregate(
        self, db_session: AsyncSession
    ) -> None:
        """Two topics cannot carry ten questions.

        The policy revisits a topic when a candidate struggles, so a two-topic
        blueprint makes a ten-question interview circle. Role demand is still
        demand for the job they are interviewing for.
        """
        thin = await _skill(db_session, "Only This")
        java = await _skill(db_session, "Java")
        spring = await _skill(db_session, "Spring")
        aws = await _skill(db_session, "AWS")

        target = await _job(db_session, skills=[(thin, SkillRequirement.REQUIRED)])
        for _ in range(MIN_POSTINGS):
            await _job(
                db_session,
                skills=[
                    (java, SkillRequirement.REQUIRED),
                    (spring, SkillRequirement.REQUIRED),
                    (aws, SkillRequirement.PREFERRED),
                ],
            )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.source is InterviewTopicSource.ROLE_DEMAND
        assert blueprint.postings > 1
        assert "Java" in blueprint.topics

    async def test_it_never_claims_the_posting_it_could_not_use(
        self, db_session: AsyncSession
    ) -> None:
        """The honesty test, and the reason `source` is not inferred.

        A job was targeted and contributed nothing. Saying "topics come from the
        posting you chose" would be a lie the interface would then repeat.
        """
        target = await _job(db_session, skills=[])

        blueprint = await blueprint_for(db_session, role="Nothing Matches This", job_id=target.id)

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.source is not InterviewTopicSource.THIS_JOB
        assert blueprint.topics == GENERIC_TOPICS

    @pytest.mark.parametrize("count", range(MIN_JOB_TOPICS))
    async def test_below_the_threshold_is_not_this_job(
        self, db_session: AsyncSession, count: int
    ) -> None:
        skills = [
            (await _skill(db_session, f"Skill {count} {n}"), SkillRequirement.REQUIRED)
            for n in range(count)
        ]
        target = await _job(db_session, skills=skills)

        blueprint = await blueprint_for(db_session, role="Unmatched Role", job_id=target.id)

        assert blueprint.source is not InterviewTopicSource.THIS_JOB

    async def test_exactly_the_threshold_is_enough(self, db_session: AsyncSession) -> None:
        # The boundary itself, so the comparison cannot quietly become `>`.
        skills = [
            (await _skill(db_session, f"Edge {n}"), SkillRequirement.REQUIRED)
            for n in range(MIN_JOB_TOPICS)
        ]
        target = await _job(db_session, skills=skills)

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.source is InterviewTopicSource.THIS_JOB


class TestTheRolePath:
    """Unchanged behaviour, pinned because this change rearranged the function."""

    async def test_demand_over_enough_postings(self, db_session: AsyncSession) -> None:
        java = await _skill(db_session, "Java")
        for _ in range(MIN_POSTINGS):
            await _job(db_session, skills=[(java, SkillRequirement.REQUIRED)])

        blueprint = await blueprint_for(db_session, role=ROLE)

        assert blueprint.source is InterviewTopicSource.ROLE_DEMAND
        assert blueprint.postings == MIN_POSTINGS
        assert blueprint.topics == ("Java",)

    async def test_too_few_postings_is_generic_and_says_how_few(
        self, db_session: AsyncSession
    ) -> None:
        """The count survives the fallback.

        "Only 2 postings match, which is too few to read demand from" is a
        better sentence than "generic", and it needs the number.
        """
        java = await _skill(db_session, "Java")
        for _ in range(MIN_POSTINGS - 1):
            await _job(db_session, skills=[(java, SkillRequirement.REQUIRED)])

        blueprint = await blueprint_for(db_session, role=ROLE)

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == MIN_POSTINGS - 1
        assert blueprint.topics == GENERIC_TOPICS

    async def test_postings_with_no_parsed_skills_are_not_demand(
        self, db_session: AsyncSession
    ) -> None:
        # Real on a corpus whose extraction has not run.
        for _ in range(MIN_POSTINGS):
            await _job(db_session, skills=[])

        blueprint = await blueprint_for(db_session, role=ROLE)

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == MIN_POSTINGS

    async def test_an_expired_posting_is_not_market_demand(
        self, db_session: AsyncSession
    ) -> None:
        # The other half of the filter: it does apply here. A sample of what
        # employers want should not be drawn from adverts nobody can apply to.
        java = await _skill(db_session, "Java")
        for _ in range(MIN_POSTINGS):
            await _job(
                db_session,
                skills=[(java, SkillRequirement.REQUIRED)],
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )

        blueprint = await blueprint_for(db_session, role=ROLE)

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == 0

    async def test_a_duplicate_posting_is_not_market_demand(
        self, db_session: AsyncSession
    ) -> None:
        # DUPLICATE rows are kept rather than deleted, so they are reachable and
        # would double-count one employer's opinion.
        java = await _skill(db_session, "Java")
        # `ck_jobs_duplicate_has_canonical` requires one, and the canonical row
        # is titled so it does not match the role -- otherwise it would be a
        # matching posting itself and the count would not be zero.
        canonical = await _job(db_session, title="Something Else Entirely")
        for _ in range(MIN_POSTINGS):
            await _job(
                db_session,
                skills=[(java, SkillRequirement.REQUIRED)],
                status=JobStatus.DUPLICATE,
                canonical_job_id=canonical.id,
            )

        blueprint = await blueprint_for(db_session, role=ROLE)

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == 0

    async def test_an_empty_role_is_generic(self, db_session: AsyncSession) -> None:
        blueprint = await blueprint_for(db_session, role="   ")

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == 0

    async def test_a_role_nothing_matches_is_generic(self, db_session: AsyncSession) -> None:
        blueprint = await blueprint_for(db_session, role="Underwater Basket Weaver")

        assert blueprint.source is InterviewTopicSource.GENERIC
        assert blueprint.postings == 0
