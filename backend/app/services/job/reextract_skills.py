"""Re-derive job skills from stored text after a taxonomy change.

The taxonomy grew by 52 entries on 2026-09-12, chosen from what the skill
extraction evaluation measured as missing. **Adding entries changes nothing that
is already stored**: `job_skills` was written by a matcher built from the old
taxonomy, so every posting mentioning Databricks, LlamaIndex or NoSQL still
carries no row for it. The improvement is invisible until the text is read again.

This is the job-side counterpart to `reparse.py`, and rests on the same promise
from `models/job.py`: *"Re-parsing with a better extractor has to be possible
without the user re-pasting anything."* The description is the source of truth;
everything derived from it can be rebuilt.

**Safe to run repeatedly, and safe to run on a taxonomy that only grew.**
`replace_for_job` fully supersedes a posting's previous reading, which is correct
here precisely because job skills carry no user edits — a job's requirements are
a fact about the posting. The candidate side is the opposite and is handled
elsewhere: `upsert_from_extraction` refuses to overwrite a row the user has
touched, which is what makes re-extraction safe there.

**Skill counts can only go up under an additive taxonomy change**, so a posting
that loses skills is a signal something else changed, and the result reports that
separately rather than averaging it away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import JobStatus
from app.models.job import Job, JobSkill
from app.repositories.job import JobSkillRepository
from app.repositories.skill import SkillRepository
from app.services.job.sections import detect_sections, section_map
from app.services.job.skills import extract_job_skills
from app.services.resume.skill_extraction import build_matcher

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReextractResult:
    """What a run did, in terms that can be checked against expectations."""

    considered: int
    changed: int
    skills_before: int
    skills_after: int
    #: Postings that came out with *fewer* skills than they went in with.
    #:
    #: Should be zero after a purely additive taxonomy change. A non-zero count
    #: means something other than the vocabulary moved — a re-parse that altered
    #: sections, or an entry that was renamed rather than added — and is worth
    #: investigating rather than accepting.
    lost_skills: int


async def reextract_job_skills(session: AsyncSession) -> ReextractResult:
    """Re-read every live posting's skills with the current taxonomy."""
    skills_repo = SkillRepository(session)
    job_skills_repo = JobSkillRepository(session)
    matcher = build_matcher(await skills_repo.load_taxonomy())

    before_total = (
        await session.scalar(
            select(func.count()).select_from(JobSkill).join(Job, Job.id == JobSkill.job_id)
        )
    ) or 0

    jobs = (
        await session.scalars(select(Job).where(Job.status == JobStatus.ACTIVE))
    ).all()

    counts: dict[uuid.UUID, int] = dict(
        (
            await session.execute(
                select(JobSkill.job_id, func.count()).group_by(JobSkill.job_id)
            )
        ).all()  # type: ignore[arg-type]
    )

    changed = 0
    lost = 0
    after_total = 0

    for job in jobs:
        text = job.description_clean or job.description_raw or ""
        by_type = section_map(detect_sections(text))
        mentions = extract_job_skills(matcher=matcher, sections=by_type, full_text=text)

        resolved = await skills_repo.get_by_names([m.canonical_name for m in mentions])
        rows = [
            (resolved[m.canonical_name].id, m.requirement, m.confidence, m.min_years)
            for m in mentions
            if m.canonical_name in resolved
        ]

        previous = counts.get(job.id, 0)
        written = await job_skills_repo.replace_for_job(job_id=job.id, rows=rows)
        after_total += written

        if written != previous:
            changed += 1
        if written < previous:
            lost += 1
            log.warning(
                "re-extraction lost skills",
                job_id=str(job.id),
                before=previous,
                after=written,
            )

    result = ReextractResult(
        considered=len(jobs),
        changed=changed,
        skills_before=before_total,
        skills_after=after_total,
        lost_skills=lost,
    )
    log.info(
        "job skills re-extracted",
        considered=result.considered,
        changed=result.changed,
        before=result.skills_before,
        after=result.skills_after,
        lost=result.lost_skills,
    )
    return result
