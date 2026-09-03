"""Company, job and job-skill data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.enums import JobStatus, SkillRequirement
from app.models.job import Company, Job, JobSkill
from app.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    model = Company

    async def get_by_normalized_name(self, normalized_name: str) -> Company | None:
        return await self.session.scalar(
            select(Company).where(Company.normalized_name == normalized_name)
        )


class JobRepository(BaseRepository[Job]):
    model = Job

    async def find_by_content_hash(self, content_hash: str) -> Job | None:
        """Stage one of duplicate detection (US-3.2 AC1).

        Returns the oldest match, which is the canonical posting: a duplicate
        should point at the original rather than at whichever copy happened to
        be found first. DUPLICATE rows are excluded so a chain never forms —
        every duplicate points directly at a live job.
        """
        return await self.session.scalar(
            select(Job)
            .where(Job.content_hash == content_hash, Job.status == JobStatus.ACTIVE)
            .order_by(Job.created_at.asc())
            .limit(1)
        )

    async def find_by_external_id(self, source: str, external_id: str) -> Job | None:
        """What makes a re-run of an import create nothing new (US-3.3 AC1)."""
        return await self.session.scalar(
            select(Job).where(Job.source == source, Job.external_id == external_id).limit(1)
        )

    async def list_active(
        self,
        *,
        query: str | None = None,
        work_mode: str | None = None,
        employment_type: str | None = None,
        experience_level: str | None = None,
        country_code: str | None = None,
        company_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        """Browse live postings, newest first. Returns `(rows, total)`.

        Expiry is read from `expires_at` rather than from a status value, so
        there is one source of truth about whether a posting is still open and
        nothing has to sweep the table to keep a second one accurate.
        """
        now = datetime.now(UTC)
        conditions = [
            Job.status == JobStatus.ACTIVE,
            (Job.expires_at.is_(None)) | (Job.expires_at > now),
        ]

        if query:
            # Title or description. ILIKE rather than full-text search: the
            # corpus is small until Phase 6 brings embeddings, and a tsvector
            # column plus its index is work that semantic search then replaces.
            pattern = f"%{query}%"
            conditions.append(Job.title.ilike(pattern) | Job.description_raw.ilike(pattern))
        if work_mode:
            conditions.append(Job.work_mode == work_mode)
        if employment_type:
            conditions.append(Job.employment_type == employment_type)
        if experience_level:
            conditions.append(Job.experience_level == experience_level)
        if country_code:
            conditions.append(Job.country_code == country_code)
        if company_id is not None:
            conditions.append(Job.company_id == company_id)

        total = (
            await self.session.scalar(select(func.count()).select_from(Job).where(*conditions))
        ) or 0

        stmt = (
            select(Job)
            .where(*conditions)
            # Newest first, with created_at as the tiebreak so an imported batch
            # that shares one posted_at still paginates deterministically.
            .order_by(Job.posted_at.desc().nullslast(), Job.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.scalars(stmt)).all())
        return rows, total

    async def count_active(self) -> int:
        return (
            await self.session.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.ACTIVE)
            )
        ) or 0


class JobSkillRepository(BaseRepository[JobSkill]):
    model = JobSkill

    async def replace_for_job(
        self,
        *,
        job_id: uuid.UUID,
        rows: Sequence[tuple[uuid.UUID, SkillRequirement, float, float | None]],
    ) -> int:
        """Write the skills a job asks for, replacing whatever was there.

        Replace rather than merge, unlike `candidate_skills`. There is no user
        edit to protect here — a job's requirements are a fact about the
        posting, and a re-parse with a better extractor should fully supersede
        the previous reading. `ON CONFLICT DO UPDATE` covers the case where the
        same skill is written twice within one parse.
        """
        if not rows:
            return 0

        await self.session.execute(
            JobSkill.__table__.delete().where(JobSkill.job_id == job_id)
        )

        from app.core.ids import uuid7

        stmt = pg_insert(JobSkill).values(
            [
                {
                    "id": uuid7(),
                    "job_id": job_id,
                    "skill_id": skill_id,
                    "requirement": requirement,
                    "extraction_confidence": confidence,
                    "min_years": min_years,
                }
                for skill_id, requirement, confidence, min_years in rows
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[JobSkill.job_id, JobSkill.skill_id],
            set_={
                "requirement": stmt.excluded.requirement,
                "extraction_confidence": stmt.excluded.extraction_confidence,
                "min_years": stmt.excluded.min_years,
            },
        )
        await self.session.execute(stmt)
        return len(rows)

    async def demand_counts(self) -> dict[uuid.UUID, int]:
        """How many active jobs require each skill.

        The input to `skills.demand_score`, which drives gap severity in Phase 7
        (US-5.1 AC2). Served by ix_job_skills_skill.
        """
        stmt = (
            select(JobSkill.skill_id, func.count())
            .join(Job, Job.id == JobSkill.job_id)
            .where(
                Job.status == JobStatus.ACTIVE,
                JobSkill.requirement == SkillRequirement.REQUIRED,
            )
            .group_by(JobSkill.skill_id)
        )
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}
