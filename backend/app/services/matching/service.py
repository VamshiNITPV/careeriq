"""Assembling the six dimensions into one score (US-4.1, ADR-005).

The whole promise of this module is one sentence from api.md: *"`contribution`
values sum to `overall_score`. The score is reproducible by hand from this
payload."* Everything below exists to keep that literally true — see
`_contribution` for where it is actually won.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.embeddings.base import EmbeddingProvider
from app.models.enums import SkillRequirement
from app.models.job import Job
from app.repositories.matching import CandidateSnapshot, MatchingRepository, SkillFacts
from app.services.matching import dimensions as dim
from app.services.matching.weights import (
    RANKING_VERSION,
    WEIGHTS,
    Dimension,
    DimensionStatus,
)

#: One decimal place on every contribution and on the total. Chosen because it
#: is what api.md's worked example shows, and because a user checking the
#: arithmetic by hand is adding six numbers off a screen — two places would make
#: that tedious for no gain in meaning.
_CONTRIBUTION_Q = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class ScoredDimension:
    """One row of the breakdown."""

    dimension: Dimension
    score: Decimal
    weight: Decimal
    contribution: Decimal
    status: DimensionStatus
    reason: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One candidate against one job.

    **The fields are deliberately the columns of `database.md`'s `job_matches`**
    — `user_id`, `job_id`, `resume_version_id`, `overall_score`, the six
    per-dimension scores, the three skill id arrays, `explanation`,
    `ranking_version`, `computed_at`. That table is not built in this phase (see
    below), but shaping the result as its row now means 6.3 adds a migration and
    an upsert without touching a line of the computation.

    **Why no table yet.** The computation is six statements and no model —
    single-digit milliseconds for one job, cheaper than the cache would be. More
    to the point, `is_stale` is specified as "set when preferences or resume
    change" and *nothing sets it*; a cache with no invalidation writer does not
    degrade, it goes quietly wrong, and ADR-006 argues against precomputing a
    score that "depends on user preferences that change at any moment". The
    performance requirement that earns a materialised table belongs to
    `/recommendations` in 6.3, where one request scores two hundred jobs.
    """

    user_id: uuid.UUID
    job_id: uuid.UUID
    #: The version the semantic dimension actually compared against — an input,
    #: not only provenance, because `candidate_embeddings` is keyed on it.
    resume_version_id: uuid.UUID
    overall_score: Decimal
    breakdown: tuple[ScoredDimension, ...]
    #: Weight of the rows that actually measured something — the honesty
    #: disclosure. See `_scored_weight`.
    scored_weight: Decimal
    skills: dim.SkillBuckets
    ranking_version: str
    computed_at: datetime
    #: False when the semantic dimension could not run. The endpoint reports
    #: this as PARTIAL, because a score missing its heaviest dimension is a
    #: different kind of answer from a complete one.
    semantic_available: bool


def _contribution(score: Decimal, weight: Decimal) -> Decimal:
    return (score * weight * 100).quantize(_CONTRIBUTION_Q)


def assemble(scores: dict[Dimension, dim.DimensionScore]) -> tuple[ScoredDimension, ...]:
    """The six dimension results as the breakdown rows.

    A module-level function rather than a method, so the one property that
    matters — the contributions summing to the total — can be swept over
    thousands of score combinations without a database anywhere near it.

    Iterating `WEIGHTS`, not `scores`, so the breakdown is always the six in
    documented weight order. Never sorted by score: a fixed order is what makes
    two payloads diffable and what turns US-4.1 AC2's by-hand check into a
    straight read down one column.
    """
    return tuple(
        ScoredDimension(
            dimension=dimension,
            score=scores[dimension].score,
            weight=weight,
            contribution=_contribution(scores[dimension].score, weight),
            status=scores[dimension].status,
            reason=scores[dimension].reason,
        )
        for dimension, weight in WEIGHTS.items()
    )


def overall(breakdown: tuple[ScoredDimension, ...]) -> Decimal:
    """The sum of the **rounded** contributions, not a separately rounded total.

    This one line is where US-4.1 AC2 is actually won. Computing the total from
    the unrounded scores and rounding it afterwards would leave it off by up to
    0.1 from the column printed beneath it, and the payload would then fail the
    single property it promises — that the user can reproduce the score by hand.
    """
    return sum((row.contribution for row in breakdown), start=Decimal("0"))


def _scored_weight(rows: tuple[ScoredDimension, ...]) -> Decimal:
    """The share of the formula that measured something about this person.

    Note the deliberate asymmetry with the score itself: a `NOT_STATED`
    education row awards a full 10 points — absence of a requirement is not a
    penalty — but contributes **nothing** here. Those points are real and they
    are not evidence, and conflating the two is what would let the interface
    claim confidence it has not earned.
    """
    return sum(
        (row.weight for row in rows if row.status is DimensionStatus.SCORED), start=Decimal("0")
    )


class MatchingService:
    """Scores one candidate against one job.

    Takes the provider only to learn *which* model's vectors to compare, exactly
    as `similar_jobs` does. **No model is ever loaded here** — the comparison is
    a cosine in SQL, which is what lets the API image stay free of torch
    (architecture.md's cold-start risk, asserted by a test).
    """

    def __init__(self, *, repo: MatchingRepository, provider: EmbeddingProvider | None) -> None:
        self._repo = repo
        self._provider = provider

    async def snapshot(self, user_id: uuid.UUID) -> CandidateSnapshot:
        """Load the candidate once.

        Exposed separately so 6.3 can score two hundred jobs against a single
        snapshot rather than reloading the profile two hundred times.
        """
        return await self._repo.candidate_snapshot(user_id)

    async def default_resume_version_id(self, user_id: uuid.UUID) -> uuid.UUID | None:
        """The primary resume's current version, else the newest resume's.

        `None` means this caller has uploaded nothing, which the endpoint
        reports as NO_RESUME rather than scoring them out of neutral defaults.
        """
        return await self._repo.default_resume_version_id(user_id)

    async def match(
        self,
        *,
        user_id: uuid.UUID,
        job: Job,
        resume_version_id: uuid.UUID,
        snapshot: CandidateSnapshot | None = None,
    ) -> MatchResult:
        """Score one job. Two queries: the cosine, and the taxonomy."""
        candidate = snapshot if snapshot is not None else await self.snapshot(user_id)

        cosine = (
            None
            if self._provider is None
            else await self._repo.candidate_job_cosine(
                resume_version_id=resume_version_id,
                job_id=job.id,
                model_name=self._provider.model_name,
            )
        )
        # Both sides in one query: the one-level rule looks up the parent of a
        # job's skill *and* of the candidate's, and either direction can produce
        # the match. The same row carries the demand score the rarity weight needs.
        facts = await self._repo.skill_facts(
            {js.skill_id for js in job.skills} | set(candidate.skill_ids)
        )
        return self._score(
            candidate=candidate,
            job=job,
            resume_version_id=resume_version_id,
            cosine=cosine,
            facts=facts,
        )

    async def match_many(
        self,
        *,
        user_id: uuid.UUID,
        jobs: Sequence[Job],
        resume_version_id: uuid.UUID,
        cosines: Mapping[uuid.UUID, Decimal],
        snapshot: CandidateSnapshot | None = None,
    ) -> list[MatchResult]:
        """Score many jobs with a fixed number of queries — three, not 2N.

        **Measured before this existed:** ranking 200 jobs took 369 ms median
        and 535 ms p95, breaching NFR-2's 500 ms budget on a corpus of 282. The
        cause was not the arithmetic — it was 400 round trips, one cosine and
        one taxonomy lookup per job. Caching that would have hidden an N+1
        behind a cache, which is the wrong repair: the first uncached request
        stays slow, and the cache then needs invalidation logic to be wrong in.

        Two changes remove it. `cosines` is passed in because **stage one already
        computed it** — the recall query orders by that very distance, so
        re-asking the database for it per job was pure waste. And the taxonomy is
        loaded once for the union of every job's skills plus the candidate's,
        which is the same one-level rule over a bigger id set.
        """
        candidate = snapshot if snapshot is not None else await self.snapshot(user_id)

        wanted: set[uuid.UUID] = set(candidate.skill_ids)
        for job in jobs:
            wanted.update(js.skill_id for js in job.skills)
        facts = await self._repo.skill_facts(wanted)

        return [
            self._score(
                candidate=candidate,
                job=job,
                resume_version_id=resume_version_id,
                cosine=cosines.get(job.id),
                facts=facts,
            )
            for job in jobs
        ]

    def _score(
        self,
        *,
        candidate: CandidateSnapshot,
        job: Job,
        resume_version_id: uuid.UUID,
        cosine: Decimal | None,
        facts: SkillFacts,
    ) -> MatchResult:
        """The formula itself, with every input already resolved.

        Synchronous and free of I/O on purpose: it is what both `match` and
        `match_many` call, so the single-job and the two-hundred-job paths can
        never drift into scoring the same pair differently. A job showing 68 in
        the recommendations list and 61 on its own page would mean one of them
        is lying, with no way for a reader to tell which.
        """
        # Sorted, and it is load-bearing rather than cosmetic. `Job.skills` is a
        # relationship with no ORDER BY, so PostgreSQL is free to return the rows
        # in any order — and two loads of the same job genuinely do differ. That
        # reaches the user as a reason string whose skills are listed
        # differently on every refresh, and it breaks the claim that two
        # payloads for the same pair are diffable. Required first, then
        # alphabetical: the order a reader would want anyway, since a required
        # skill they lack matters more than a preferred one.
        requirements = tuple(
            sorted(
                (
                    dim.SkillRequirementInput(
                        skill_id=js.skill_id, name=js.skill.name, requirement=js.requirement
                    )
                    for js in job.skills
                ),
                key=lambda req: (
                    req.requirement is not SkillRequirement.REQUIRED,
                    req.name.casefold(),
                ),
            )
        )
        buckets = dim.classify_skills(
            requirements=requirements,
            candidate_skill_ids=candidate.skill_ids,
            parent_of=facts.parent_of,
        )
        user_id = candidate.user_id

        now = datetime.now(UTC)
        # An explicit None test, not `or`. A fresher with a stated 0 years is a
        # real answer and `Decimal("0") or fallback` would silently discard it.
        candidate_years = candidate.years_of_experience
        if candidate_years is None:
            candidate_years = dim.years_from_history(candidate.work_spans, today=now.date())

        scores = {
            Dimension.SEMANTIC: dim.score_semantic(cosine),
            Dimension.SKILL: dim.score_skill(
                buckets=buckets,
                has_candidate_skills=bool(candidate.skill_ids),
                demand=facts.demand,
            ),
            Dimension.EXPERIENCE: dim.score_experience(
                candidate_years=candidate_years,
                min_years=job.min_years_experience,
                max_years=job.max_years_experience,
            ),
            Dimension.EDUCATION: dim.score_education(
                candidate_level=candidate.highest_education,
                required_level=job.min_education,
            ),
            Dimension.LOCATION: dim.score_location(
                job_location=job.location,
                job_country=job.country_code,
                job_work_mode=job.work_mode,
                candidate_location=candidate.location,
                candidate_country=candidate.country_code,
                preferred_locations=candidate.preferred_locations,
                preferred_work_modes=candidate.preferred_work_modes,
                open_to_relocation=candidate.open_to_relocation,
            ),
            Dimension.SALARY: dim.score_salary(
                job_salary_min=job.salary_min,
                job_salary_max=job.salary_max,
                job_currency=job.salary_currency,
                job_period=job.salary_period,
                candidate_minimum=candidate.min_salary_expectation,
                candidate_currency=candidate.salary_currency,
            ),
        }

        breakdown = assemble(scores)

        return MatchResult(
            user_id=user_id,
            job_id=job.id,
            resume_version_id=resume_version_id,
            overall_score=overall(breakdown),
            breakdown=breakdown,
            scored_weight=_scored_weight(breakdown),
            skills=buckets,
            ranking_version=RANKING_VERSION,
            computed_at=now,
            semantic_available=cosine is not None,
        )
