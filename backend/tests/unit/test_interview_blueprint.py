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
from decimal import Decimal

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
from app.models.skill import CandidateSkill, Skill
from app.services.interview.blueprint import (
    MAX_TOPICS,
    MIN_JOB_TOPICS,
    MIN_POSTINGS,
    blueprint_for,
)
from app.services.interview.policy import GENERIC_TOPICS

ROLE = "Backend Engineer"


@pytest.fixture
async def user_id(registered_user: dict[str, object]) -> uuid.UUID:
    """The id of a real user row, for CandidateSkill's foreign key.

    `registered_user` returns the response body rather than a model, and the FK
    on `candidate_skills.user_id` is RESTRICT -- so an invented uuid fails on
    insert rather than producing a quietly empty held set.
    """
    return uuid.UUID(str(registered_user["user"]["id"]))  # type: ignore[index]


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
    confidences: Sequence[Decimal] | None = None,
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
    for index, (skill, requirement) in enumerate(skills):
        job.skills.append(
            JobSkill(
                skill_id=skill.id,
                requirement=requirement,
                extraction_confidence=(
                    confidences[index] if confidences is not None else None
                ),
            )
        )
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


class TestWhenEverySkillIsRequired:
    """The case a corpus hides and one posting exposes.

    `job/skills.py` marks REQUIRED for the Requirements section, the
    Responsibilities section *and* any section it could not identify, so a real
    posting routinely carries thirty REQUIRED skills. Across 48 adverts the
    summed weight still separates them; within one it is identical for every
    row, and the sort falls through to whatever comes next.

    This class exists because the first live comparison returned "Agile, CI/CD,
    Data Processing, Docker, ETL, Embeddings, FastAPI, Flask" for an AI Engineer
    posting that names Large Language Models, RAG and Python -- `MAX_TOPICS` had
    cut the substance off at the letter F. No unit test caught it, because none
    of them had more than a handful of equally-weighted skills.
    """

    async def test_confidence_orders_what_the_weight_cannot(
        self, db_session: AsyncSession
    ) -> None:
        # Alphabetically last, and the one the posting asked for most clearly.
        substantive = await _skill(db_session, "Zebra Systems")
        incidental = [await _skill(db_session, f"Aardvark {n}") for n in range(3)]

        target = await _job(
            db_session,
            skills=[
                (substantive, SkillRequirement.REQUIRED),
                *[(skill, SkillRequirement.REQUIRED) for skill in incidental],
            ],
            confidences=[Decimal("0.99"), Decimal("0.60"), Decimal("0.60"), Decimal("0.60")],
        )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.topics[0] == "Zebra Systems"

    async def test_the_cut_keeps_the_clearest_not_the_earliest(
        self, db_session: AsyncSession
    ) -> None:
        """The actual failure, in miniature.

        More skills than `MAX_TOPICS`, all REQUIRED, with the meaningful ones
        sorting last by name. Without a confidence tiebreak the interview
        examines the alphabet.
        """
        wanted = [await _skill(db_session, f"Zulu {n}") for n in range(3)]
        filler = [await _skill(db_session, f"Alpha {n}") for n in range(MAX_TOPICS)]

        target = await _job(
            db_session,
            skills=[
                *[(skill, SkillRequirement.REQUIRED) for skill in wanted],
                *[(skill, SkillRequirement.REQUIRED) for skill in filler],
            ],
            confidences=[
                *[Decimal("0.99")] * len(wanted),
                *[Decimal("0.60")] * len(filler),
            ],
        )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert len(blueprint.topics) == MAX_TOPICS
        for skill in wanted:
            assert skill.name in blueprint.topics, skill.name

    async def test_requirement_still_outranks_confidence(
        self, db_session: AsyncSession
    ) -> None:
        # Confidence is the tiebreak, not the primary. A PREFERRED skill the
        # parser was certain about is still preferred, not required.
        sure_but_optional = await _skill(db_session, "AAA Preferred")
        needed = [await _skill(db_session, f"ZZZ Required {n}") for n in range(3)]

        target = await _job(
            db_session,
            skills=[
                (sure_but_optional, SkillRequirement.PREFERRED),
                *[(skill, SkillRequirement.REQUIRED) for skill in needed],
            ],
            confidences=[Decimal("0.99"), *[Decimal("0.60")] * len(needed)],
        )

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.topics[-1] == "AAA Preferred"

    async def test_a_missing_confidence_does_not_drop_the_skill(
        self, db_session: AsyncSession
    ) -> None:
        # The column is nullable, and a null must sort low rather than removing
        # the row from the result entirely.
        skills = [
            (await _skill(db_session, f"Unscored {n}"), SkillRequirement.REQUIRED)
            for n in range(MIN_JOB_TOPICS)
        ]
        target = await _job(db_session, skills=skills, confidences=None)

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.source is InterviewTopicSource.THIS_JOB
        assert len(blueprint.topics) == MIN_JOB_TOPICS


async def _holds(session: AsyncSession, user_id: uuid.UUID, *skills: Skill) -> None:
    """Give the candidate these skills, the way the extractor would."""
    for skill in skills:
        session.add(CandidateSkill(id=uuid7(), user_id=user_id, skill_id=skill.id))
    await session.flush()


class TestTheGapComesFirst:
    """Demand says what the job wants; it says nothing about this candidate.

    A list built from demand alone examines six years of somebody's experience as
    readily as something they have never touched, and the questions worth
    rehearsing are the ones they would actually struggle with. `skill/gaps.py`
    already knows which those are, and this reuses its answer rather than forming
    a second opinion -- so the gap a user was told to close is the gap they get
    asked about.
    """

    async def test_a_skill_they_lack_outranks_one_they_have(
        self, db_session: AsyncSession, user_id: uuid.UUID
    ) -> None:
        known = await _skill(db_session, "AAA Known")
        unknown = await _skill(db_session, "ZZZ Unknown")
        filler = await _skill(db_session, "MMM Filler")
        await _holds(db_session, user_id, known)

        target = await _job(
            db_session,
            skills=[
                (known, SkillRequirement.REQUIRED),
                (unknown, SkillRequirement.REQUIRED),
                (filler, SkillRequirement.REQUIRED),
            ],
        )

        blueprint = await blueprint_for(
            db_session, role=ROLE, job_id=target.id, user_id=user_id
        )

        # The one they have is last, despite sorting first by name and being
        # REQUIRED like the others. Both gaps tie with each other at the same
        # multiplier, so the name decides between *them* -- which is why the
        # assertion is about position relative to the known skill rather than
        # about index 0.
        assert blueprint.topics[-1] == "AAA Known"
        assert blueprint.topics.index("ZZZ Unknown") < blueprint.topics.index("AAA Known")
        assert blueprint.topics.index("MMM Filler") < blueprint.topics.index("AAA Known")

    async def test_the_job_still_decides_what_matters_most(
        self, db_session: AsyncSession, user_id: uuid.UUID
    ) -> None:
        """A preference, not a filter, and this is what keeps it one.

        A PREFERRED skill they lack must still rank below a REQUIRED skill they
        have. Otherwise the interview drifts off what the employer asked for and
        onto whatever the candidate happens to be weakest at.
        """
        required_known = await _skill(db_session, "Required Known")
        preferred_unknown = await _skill(db_session, "Preferred Unknown")
        filler = await _skill(db_session, "Filler")
        await _holds(db_session, user_id, required_known)

        target = await _job(
            db_session,
            skills=[
                (required_known, SkillRequirement.REQUIRED),
                (preferred_unknown, SkillRequirement.PREFERRED),
                (filler, SkillRequirement.REQUIRED),
            ],
        )

        blueprint = await blueprint_for(
            db_session, role=ROLE, job_id=target.id, user_id=user_id
        )

        assert blueprint.topics.index("Required Known") < blueprint.topics.index(
            "Preferred Unknown"
        )

    async def test_a_related_skill_sits_between_the_two(
        self, db_session: AsyncSession, user_id: uuid.UUID
    ) -> None:
        """Their React against the job's JavaScript is neither gap nor strength.

        One taxonomy level, the same partial credit `skill/gaps.py` gives and the
        ranking's skill dimension gives -- treating a related skill as a total
        absence overstates the gap.
        """
        parent = await _skill(db_session, "Parent Skill")
        child = Skill(
            id=uuid7(),
            name="Child Skill",
            normalized_name=normalize_skill_text("Child Skill"),
            category="tool",
            aliases=[],
            parent_skill_id=parent.id,
        )
        db_session.add(child)
        await db_session.flush()

        missing = await _skill(db_session, "Plainly Missing")
        held = await _skill(db_session, "Plainly Held")
        # The child, so the job's parent is partial credit; and one plain hold.
        await _holds(db_session, user_id, child, held)

        target = await _job(
            db_session,
            skills=[
                (parent, SkillRequirement.REQUIRED),
                (missing, SkillRequirement.REQUIRED),
                (held, SkillRequirement.REQUIRED),
            ],
        )

        blueprint = await blueprint_for(
            db_session, role=ROLE, job_id=target.id, user_id=user_id
        )

        assert blueprint.topics.index("Plainly Missing") < blueprint.topics.index("Parent Skill")
        assert blueprint.topics.index("Parent Skill") < blueprint.topics.index("Plainly Held")

    async def test_it_lifts_the_role_aggregate_too(
        self, db_session: AsyncSession, user_id: uuid.UUID
    ) -> None:
        """Why the multiplier is multiplicative.

        A flat bonus big enough to matter against one posting's weight of 1.0 is
        invisible against a sum over forty-eight, so the same constant would
        change the targeted path and do nothing here.
        """
        known = await _skill(db_session, "AAA Known")
        unknown = await _skill(db_session, "ZZZ Unknown")
        await _holds(db_session, user_id, known)
        for _ in range(MIN_POSTINGS):
            await _job(
                db_session,
                skills=[
                    (known, SkillRequirement.REQUIRED),
                    (unknown, SkillRequirement.REQUIRED),
                ],
            )

        blueprint = await blueprint_for(db_session, role=ROLE, user_id=user_id)

        assert blueprint.source is InterviewTopicSource.ROLE_DEMAND
        assert blueprint.topics[0] == "ZZZ Unknown"

    async def test_a_rejected_skill_is_a_gap_again(
        self, db_session: AsyncSession, user_id: uuid.UUID
    ) -> None:
        # The user told us the extractor was wrong about this one. `skill/gaps.py`
        # reads `is_rejected` the same way, which is the point of sharing it.
        rejected = await _skill(db_session, "AAA Rejected")
        db_session.add(
            CandidateSkill(
                id=uuid7(), user_id=user_id, skill_id=rejected.id, is_rejected=True
            )
        )
        await db_session.flush()
        first = await _skill(db_session, "MMM Filler")
        second = await _skill(db_session, "NNN Filler")

        target = await _job(
            db_session,
            skills=[
                (rejected, SkillRequirement.REQUIRED),
                (first, SkillRequirement.REQUIRED),
                (second, SkillRequirement.REQUIRED),
            ],
        )

        blueprint = await blueprint_for(
            db_session, role=ROLE, job_id=target.id, user_id=user_id
        )

        assert blueprint.topics[0] == "AAA Rejected"

    async def test_without_a_user_the_ordering_is_the_job_alone(
        self, db_session: AsyncSession
    ) -> None:
        # Scripts and the evaluation harness call this with no user. It must not
        # require one, and without one the result is what it was before the gap.
        skills = [
            (await _skill(db_session, f"Plain {n}"), SkillRequirement.REQUIRED)
            for n in range(MIN_JOB_TOPICS)
        ]
        target = await _job(db_session, skills=skills)

        blueprint = await blueprint_for(db_session, role=ROLE, job_id=target.id)

        assert blueprint.topics == ("Plain 0", "Plain 1", "Plain 2")
