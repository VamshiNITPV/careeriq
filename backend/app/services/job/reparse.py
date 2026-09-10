"""Re-derive the parsed fields of existing jobs from their stored text.

`jobs.description_raw` is never mutated, and `models/job.py` says why:
*"Re-parsing with a better extractor has to be possible without the user
re-pasting anything, which means the original text is the source of truth and
everything else on the row is derived."* This is the first time that promise is
collected on.

Written for the parser improvements measured in the Phase 6 quality pass: 131 of
286 active postings produced neither `responsibilities` nor `requirements`,
because their headings were not in the vocabulary or their sections were prose
rather than bullets. Those jobs were embedded from the whole description instead.

**Only derived fields are touched.** `description_raw` and `content_hash` are
left exactly as they are — the hash keys duplicate detection, and changing it
during a re-parse would make every posting look new and break the idempotent
import `(source, external_id)` relies on.

Changing `responsibilities` or `requirements` moves `updated_at`, and that is
deliberate: the embedding backlog query compares `jobs.updated_at` against
`job_embeddings.created_at`, so a job whose document changed re-embeds on the
next worker tick with no extra bookkeeping here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.job.sections import (
    JobSectionType,
    detect_sections,
    extract_bullets,
    section_map,
)

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReparseResult:
    """What a re-parse pass changed.

    `gained_sections` is the number the quality pass is actually judged on —
    postings that had neither array and now have at least one, so they stop being
    embedded from their whole description.
    """

    considered: int
    changed: int
    gained_sections: int
    still_empty: int


async def reparse_jobs(session: AsyncSession, *, batch_size: int = 1000) -> ReparseResult:
    """Re-run section extraction over active postings.

    Does not commit — the caller owns the transaction, as everywhere else.
    """
    jobs = list(
        (
            await session.scalars(
                select(Job).where(Job.status == JobStatus.ACTIVE).limit(batch_size)
            )
        ).all()
    )

    changed = 0
    gained = 0
    still_empty = 0

    for job in jobs:
        had_nothing = not job.responsibilities and not job.requirements

        body = job.description_clean or job.description_raw or ""
        by_type = section_map(detect_sections(body))
        responsibilities = extract_bullets(by_type.get(JobSectionType.RESPONSIBILITIES, ""))
        requirements = extract_bullets(by_type.get(JobSectionType.REQUIREMENTS, ""))

        if responsibilities == job.responsibilities and requirements == job.requirements:
            if had_nothing:
                still_empty += 1
            continue

        job.responsibilities = responsibilities
        job.requirements = requirements
        changed += 1
        if had_nothing and (responsibilities or requirements):
            gained += 1
        elif not responsibilities and not requirements:
            still_empty += 1

    await session.flush()
    log.info(
        "jobs reparsed",
        considered=len(jobs),
        changed=changed,
        gained_sections=gained,
        still_empty=still_empty,
    )
    return ReparseResult(
        considered=len(jobs), changed=changed, gained_sections=gained, still_empty=still_empty
    )
