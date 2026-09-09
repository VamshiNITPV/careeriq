"""Everything the ranking formula reads about one candidate.

Its own repository rather than five calls across `user`, `skill`, `career` and
`resume`, because the scorer needs all of it at once and needs it consistent:
five separate round trips would also be five separate opportunities for an N+1
once 6.3 scores two hundred jobs per request. Assembled here as a snapshot the
service can hold and reuse across every job it scores.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import EducationRecord, WorkExperience
from app.models.enums import EducationLevel, WorkMode
from app.models.profile import Profile
from app.models.resume import Resume
from app.models.skill import CandidateSkill, Skill


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    """One candidate, reduced to the fields the six dimensions read.

    Deliberately plain values, not ORM instances. The scorers are pure functions
    over data (see `services/matching/dimensions.py`), and handing them detached
    ORM objects would make every unit test need a database.
    """

    user_id: uuid.UUID
    skill_ids: frozenset[uuid.UUID] = frozenset()

    years_of_experience: Decimal | None = None
    #: `(start_date, end_date, is_current)` per role, for the years fallback.
    work_spans: tuple[tuple[date | None, date | None, bool], ...] = ()

    highest_education: EducationLevel | None = None

    location: str | None = None
    country_code: str | None = None
    preferred_locations: tuple[str, ...] = ()
    preferred_work_modes: tuple[WorkMode, ...] = ()
    open_to_relocation: bool = False

    min_salary_expectation: Decimal | None = None
    salary_currency: str | None = None

    #: Populated by `taxonomy_parents`, keyed by skill id. Empty until asked
    #: for, because it depends on which job is being scored.
    parent_of: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)


class MatchingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def candidate_snapshot(self, user_id: uuid.UUID) -> CandidateSnapshot:
        profile = await self.session.scalar(select(Profile).where(Profile.user_id == user_id))

        skill_ids = frozenset(
            (
                await self.session.scalars(
                    select(CandidateSkill.skill_id).where(CandidateSkill.user_id == user_id)
                )
            ).all()
        )

        work_spans = tuple(
            (row.start_date, row.end_date, row.is_current)
            for row in (
                await self.session.execute(
                    select(
                        WorkExperience.start_date,
                        WorkExperience.end_date,
                        WorkExperience.is_current,
                    ).where(WorkExperience.user_id == user_id)
                )
            ).all()
        )

        if profile is None:
            return CandidateSnapshot(user_id=user_id, skill_ids=skill_ids, work_spans=work_spans)

        return CandidateSnapshot(
            user_id=user_id,
            skill_ids=skill_ids,
            years_of_experience=profile.years_of_experience,
            work_spans=work_spans,
            highest_education=profile.highest_education
            or await self._highest_education_on_record(user_id),
            location=profile.location,
            country_code=profile.country_code,
            preferred_locations=tuple(profile.preferred_locations),
            preferred_work_modes=tuple(profile.preferred_work_modes),
            open_to_relocation=profile.open_to_relocation,
            min_salary_expectation=profile.min_salary_expectation,
            salary_currency=profile.salary_currency,
        )

    async def _highest_education_on_record(self, user_id: uuid.UUID) -> EducationLevel | None:
        """The best qualification among the parsed education rows.

        A fallback for `Profile.highest_education`, which is unset on every
        profile today and has no editor anywhere in the interface. Ordering
        happens in Python on `EducationLevel.rank` rather than in SQL, because
        the Postgres enum's declaration order is not what `rank` promises — the
        enum defines `rank` explicitly *so that* reordering members cannot
        silently change ranking, and sorting on the database's own ordering
        would reintroduce exactly the coupling that guards against.
        """
        levels = (
            await self.session.scalars(
                select(EducationRecord.education_level).where(
                    EducationRecord.user_id == user_id,
                    EducationRecord.education_level.is_not(None),
                )
            )
        ).all()
        if not levels:
            return None
        return max(levels, key=lambda level: level.rank)

    async def taxonomy_parents(
        self, skill_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID | None]:
        """Immediate parent of each of these skills, in one query.

        The one-level rule in `classify_skills` needs the parent of every skill
        on both sides at once. Fetching them per requirement would be an N+1 in
        the request path, and 6.3 multiplies that by two hundred jobs.
        """
        if not skill_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Skill.id, Skill.parent_skill_id).where(Skill.id.in_(skill_ids))
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    #: Cosine between one resume version's vector and one job's, computed in the
    #: database. **No vector crosses the wire** — both are scalar subqueries, so
    #: 1,536 floats stay where they are, exactly as `find_similar` does it.
    #:
    #: Keyed on the **resume version**, because that is what
    #: `candidate_embeddings` is keyed on. So `?resume_version_id=` genuinely
    #: changes the answer: two versions of the same resume can score the same
    #: job differently, which is the whole point of being able to ask.
    #:
    #: The join on `(model_name, model_version)` is the point of the statement:
    #: comparing vectors produced by two different models is not merely
    #: inaccurate, it is meaningless, and requiring equality here makes it
    #: structurally impossible rather than something to remember. During a
    #: backfill that means no row rather than a wrong number, which the caller
    #: reports honestly as "not compared yet".
    #:
    #: Vectors are stored L2-normalised, so `1 - (a <=> b)` is the cosine.
    _COSINE = text("""
        SELECT 1 - (ce.embedding <=> je.embedding)
        FROM candidate_embeddings ce
        JOIN job_embeddings je
          ON je.model_name = ce.model_name
         AND je.model_version = ce.model_version
        WHERE ce.resume_version_id = :resume_version_id
          AND je.job_id = :job_id
          AND ce.model_name = :model_name
        LIMIT 1
    """)

    async def candidate_job_cosine(
        self, *, resume_version_id: uuid.UUID, job_id: uuid.UUID, model_name: str
    ) -> Decimal | None:
        """Cosine similarity, or `None` when either side is not indexed yet."""
        value = await self.session.scalar(
            self._COSINE,
            {
                "resume_version_id": resume_version_id,
                "job_id": job_id,
                "model_name": model_name,
            },
        )
        return None if value is None else Decimal(str(value))

    async def default_resume_version_id(self, user_id: uuid.UUID) -> uuid.UUID | None:
        """Which resume the score is computed against.

        The primary resume's current version, else the newest resume's. This is
        a real input, not just provenance: `candidate_embeddings` is keyed on
        the version, so the semantic dimension compares *this* version's vector.
        Recording it on the result is also what lets `job_matches` be keyed by
        resume version in 6.3, and what makes a stored score interpretable a
        month later.
        """
        stmt = (
            select(Resume.current_version_id)
            .where(
                Resume.user_id == user_id,
                Resume.deleted_at.is_(None),
                Resume.current_version_id.is_not(None),
            )
            .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)
