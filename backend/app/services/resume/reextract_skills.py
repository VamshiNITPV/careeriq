"""Re-derive candidate skills from stored resume text after a taxonomy change.

The counterpart to `services/job/reextract_skills.py`, and deliberately a
different shape, because this side touches something the job side does not: a
person's own profile.

**Additive only. Nothing is removed, ever.** The job version calls
`replace_for_job`, which is right there — a posting's requirements are a fact
about the posting and a better reading should supersede the old one. A profile is
not that. It holds skills the user confirmed, skills they typed in themselves,
and skills they deleted on purpose, and none of those are this function's to
reconsider. So the only write is `upsert_from_extraction`, whose
`WHERE NOT is_user_verified` clause refuses to touch a row the user has marked
(US-2.4 AC2).

That still leaves one thing this cannot know: **a skill the user deleted will
come back** if the text still mentions it, because a deletion removes the row
rather than recording a decision. That is a real limitation and it is the
behaviour a user already reported once — "when I delete the file why those
extracted skills will come again". Recording rejections is the fix, and it is a
schema change rather than something to paper over here. Until then this runs only
when a taxonomy change makes it worth the cost, not on a schedule.

Written for the 52 entries added on 2026-09-12: skills like `Databricks`,
`LlamaIndex` and `NoSQL` were invisible to the matcher that produced the stored
rows, so the improvement is unreachable until the text is read again.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.resume import Resume, ResumeVersion
from app.models.skill import Skill
from app.repositories.skill import CandidateSkillRepository, SkillRepository
from app.services.resume.sections import detect_sections, section_map
from app.services.resume.skill_extraction import build_matcher, extract_skills

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReextractResult:
    versions: int
    skipped_no_text: int
    #: Rows inserted or refreshed. Never a removal.
    written: int
    #: Rows left alone because the user had verified them.
    protected: int


async def reextract_candidate_skills(session: AsyncSession) -> ReextractResult:
    """Re-read every current resume version with the current taxonomy."""
    skills_repo = SkillRepository(session)
    candidate_skills = CandidateSkillRepository(session)
    taxonomy = await skills_repo.load_taxonomy()
    if not taxonomy:
        raise RuntimeError("The skill taxonomy is empty; run the seeder first.")
    matcher = build_matcher(taxonomy)
    generic = await skills_repo.generic_names()

    # Only the version each resume currently points at. Older versions are
    # history: re-deriving skills from a resume the user has already replaced
    # would push superseded claims back onto their profile.
    versions = (
        await session.scalars(
            select(ResumeVersion)
            .join(Resume, Resume.current_version_id == ResumeVersion.id)
            .where(Resume.deleted_at.is_(None))
        )
    ).all()

    written = 0
    skipped = 0
    protected = 0

    for version in versions:
        text = version.raw_text
        if not text:
            # A version whose text was never stored, or a parse that failed.
            # Nothing to re-read; re-uploading is the only route and that is the
            # user's call.
            skipped += 1
            continue

        by_type = section_map(detect_sections(text))
        found = extract_skills(
            matcher=matcher, sections=by_type, full_text=text, generic_names=generic
        )
        # `needs_review` matches the pipeline: a low-confidence mention is
        # surfaced for the user to accept, never written to their profile.
        candidates = [c for c in found if not c.needs_review]

        resolved = await skills_repo.get_by_names([c.canonical_name for c in candidates])
        user_id = (await session.get(Resume, version.resume_id)).user_id  # type: ignore[union-attr]

        for candidate in candidates:
            skill: Skill | None = resolved.get(candidate.canonical_name)
            if skill is None:
                continue
            if await candidate_skills.upsert_from_extraction(
                user_id=user_id,
                skill_id=skill.id,
                confidence=Decimal(str(candidate.confidence)),
                source_version_id=version.id,
            ):
                written += 1
            else:
                # The row exists and is user-verified, so the write was refused.
                # Counted rather than ignored: it is the number that shows the
                # protection is doing something.
                protected += 1

    result = ReextractResult(
        versions=len(versions),
        skipped_no_text=skipped,
        written=written,
        protected=protected,
    )
    log.info(
        "candidate skills re-extracted",
        versions=result.versions,
        written=result.written,
        protected=result.protected,
        skipped=result.skipped_no_text,
    )
    return result
