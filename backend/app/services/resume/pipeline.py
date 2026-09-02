"""The resume processing pipeline (ADR-009).

    stored -> EXTRACTING -> PARSING -> COMPLETE
                     \\-> FAILED (always with a reason)

Runs outside the request. It therefore opens **its own database session**: the
request's session is closed the moment the response is sent, and reusing it here
would fail on the first query in a way that only shows under real timing.

The whole run is idempotent. A retried task must not create duplicate skill rows
or a second profile — which is why skill writes go through an upsert keyed on
(user_id, skill_id) rather than an insert.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.integrations.storage import ObjectStorage, get_object_storage
from app.models.enums import ProcessingStatus
from app.models.resume import ResumeVersion
from app.models.skill import Skill
from app.repositories.resume import ResumeRepository, ResumeVersionRepository
from app.repositories.skill import CandidateSkillRepository, SkillRepository
from app.services.file_validation import DocumentType
from app.services.resume.extraction import UnextractableDocumentError, extract_text
from app.services.resume.sections import SectionType, detect_sections, section_map
from app.services.resume.skill_extraction import (
    REVIEW_THRESHOLD,
    build_matcher,
    extract_skills,
    parse_skills_list,
)

log = get_logger(__name__)


@dataclass(slots=True)
class PipelineResult:
    version_id: uuid.UUID
    status: ProcessingStatus
    characters_extracted: int = 0
    sections_detected: int = 0
    skills_written: int = 0
    skills_for_review: int = 0
    unknown_terms: int = 0
    error: str | None = None


async def _set_status(
    session: AsyncSession,
    version: ResumeVersion,
    status: ProcessingStatus,
    *,
    error: str | None = None,
) -> None:
    """Persist a stage transition immediately.

    Committed as it happens rather than at the end, so a client polling the task
    sees real progress and a crash leaves the last completed stage recorded
    rather than a row still claiming PENDING.
    """
    version.processing_status = status
    if error is not None:
        version.processing_error = error
    if status in (ProcessingStatus.COMPLETE, ProcessingStatus.FAILED):
        version.processed_at = datetime.now(UTC)
    await session.commit()


async def process_resume_version(
    version_id: uuid.UUID,
    *,
    session: AsyncSession | None = None,
    storage: ObjectStorage | None = None,
) -> PipelineResult:
    """Parse one uploaded resume. Never raises.

    Failures are recorded on the row and returned, because the caller is a
    background task with nowhere to propagate an exception to — an unhandled one
    would vanish into the event loop and leave the version stuck mid-pipeline
    with no explanation (US-2.2 AC2).

    `session` and `storage` are injectable, and both default to the process-wide
    instances that the background task uses. Tests supply their own: a test's
    rows live in an uncommitted transaction that a separate connection cannot
    see, and its uploads live in a temporary directory rather than the
    configured store — so a pipeline hard-wired to the globals would find
    neither.
    """
    storage = storage or get_object_storage()

    if session is not None:
        return await _process(session, storage, version_id)

    async with get_session_factory()() as own_session:
        return await _process(own_session, storage, version_id)


async def _process(
    session: AsyncSession, storage: ObjectStorage, version_id: uuid.UUID
) -> PipelineResult:
    versions = ResumeVersionRepository(session)
    version = await versions.get(version_id)

    if version is None:
        log.error("pipeline: version not found", version_id=str(version_id))
        return PipelineResult(version_id, ProcessingStatus.FAILED, error="not_found")

    if version.processing_status is ProcessingStatus.COMPLETE:
        # Idempotency: a duplicate delivery must not redo the work.
        log.info("pipeline: already complete, skipping", version_id=str(version_id))
        return PipelineResult(version_id, ProcessingStatus.COMPLETE)

    try:
        return await _run(session, storage, version)
    except Exception as exc:
        log.exception(
            "pipeline: unexpected failure",
            version_id=str(version_id),
            error_type=type(exc).__name__,
        )
        await session.rollback()
        # Re-fetch: the rollback detached whatever state the failed run had.
        version = await ResumeVersionRepository(session).get(version_id)
        if version is not None:
            await _set_status(
                session,
                version,
                ProcessingStatus.FAILED,
                error="An unexpected error occurred while processing this document.",
            )
        return PipelineResult(version_id, ProcessingStatus.FAILED, error=str(exc))


async def _run(
    session: AsyncSession, storage: ObjectStorage, version: ResumeVersion
) -> PipelineResult:
    result = PipelineResult(version.id, ProcessingStatus.EXTRACTING)

    # ------------------------------------------------------------ extract
    await _set_status(session, version, ProcessingStatus.EXTRACTING)

    content = await storage.get(version.storage_key)
    document_type = (
        DocumentType.PDF if version.mime_type == DocumentType.PDF.value else DocumentType.DOCX
    )

    try:
        extracted = extract_text(content=content, document_type=document_type)
    except UnextractableDocumentError as exc:
        # Expected and user-actionable: a scan, an image-only PDF, or an
        # encrypted file. The message is written to the row so the UI can show
        # something specific instead of "processing failed".
        log.info("pipeline: document unextractable", version_id=str(version.id))
        await _set_status(session, version, ProcessingStatus.FAILED, error=exc.message)
        return PipelineResult(version.id, ProcessingStatus.FAILED, error=exc.code)

    version.raw_text = extracted.text
    result.characters_extracted = extracted.character_count

    # ------------------------------------------------------------ sections
    await _set_status(session, version, ProcessingStatus.PARSING)

    sections = detect_sections(extracted.text)
    by_type = section_map(sections)
    result.sections_detected = len(sections)

    version.parsed_sections = {
        "extractor": extracted.extractor,
        "page_count": extracted.page_count,
        "character_count": extracted.character_count,
        "sections": [
            {
                "type": section.type.value,
                "heading": section.heading,
                "start": section.start,
                "end": section.end,
                "length": len(section.text),
            }
            for section in sections
        ],
    }

    # ------------------------------------------------------------ skills
    skills_repo = SkillRepository(session)
    taxonomy = await skills_repo.load_taxonomy()

    if not taxonomy:
        # Seeding has not run. Better to say so loudly than to silently report a
        # resume with no skills, which looks like a parser failure.
        log.error("pipeline: skill taxonomy is empty; run the seeder")

    matcher = build_matcher(taxonomy)
    candidates = extract_skills(matcher=matcher, sections=by_type, full_text=extracted.text)

    accepted = [c for c in candidates if not c.needs_review]
    for_review = [c for c in candidates if c.needs_review]
    result.skills_for_review = len(for_review)

    skill_rows = await skills_repo.get_by_names([c.canonical_name for c in accepted])
    candidate_skills = CandidateSkillRepository(session)

    written = 0
    for candidate in accepted:
        skill: Skill | None = skill_rows.get(candidate.canonical_name)
        if skill is None:
            continue
        if await candidate_skills.upsert_from_extraction(
            user_id=version.resume.user_id,
            skill_id=skill.id,
            confidence=Decimal(str(candidate.confidence)),
            source_version_id=version.id,
        ):
            written += 1
    result.skills_written = written

    # Terms in an explicit skills block that the taxonomy does not know. Recorded
    # for review only — auto-creating a skill per comma-separated fragment would
    # fill the taxonomy with parser noise (ml.md section 2.4).
    known = {form for forms in taxonomy.values() for form in forms}
    unknown_terms = [
        term for term in parse_skills_list(by_type.get(SectionType.SKILLS, "")) if term not in known
    ]
    result.unknown_terms = len(unknown_terms)

    version.parsed_entities = {
        "skills": [
            {
                "name": c.canonical_name,
                "confidence": c.confidence,
                "mentions": c.mention_count,
                "section": c.best_section.value,
                "matched": list(c.matched_texts),
                "span": list(c.first_span),
                "accepted": not c.needs_review,
            }
            for c in candidates
        ],
        "unknown_terms": unknown_terms[:50],
        "review_threshold": REVIEW_THRESHOLD,
    }

    # ------------------------------------------------------------ finish
    await ResumeRepository(session).set_current_version(version.resume_id, version.id)
    await _set_status(session, version, ProcessingStatus.COMPLETE)

    result.status = ProcessingStatus.COMPLETE
    log.info(
        "pipeline: complete",
        version_id=str(version.id),
        characters=result.characters_extracted,
        sections=result.sections_detected,
        skills_written=result.skills_written,
        skills_for_review=result.skills_for_review,
        unknown_terms=result.unknown_terms,
    )
    return result


async def seed_skill_taxonomy(session: AsyncSession) -> int:
    """Load the seed taxonomy. Idempotent, so it is safe to run on every start."""
    from app.data.skill_taxonomy import SEED_SKILLS

    repository = SkillRepository(session)

    rows = [
        {
            "id": uuid7(),
            "name": seed.name,
            "normalized_name": seed.normalized_name,
            "category": seed.category,
            "aliases": seed.normalized_aliases,
            "is_verified": True,
        }
        for seed in SEED_SKILLS
    ]
    inserted = await repository.upsert_many(rows)
    await session.flush()

    # Parents are linked in a second pass: a skill's parent may appear later in
    # the list than the child, so it cannot be resolved during the insert.
    by_name = await repository.get_by_names([s.name for s in SEED_SKILLS])
    linked = 0
    for seed in SEED_SKILLS:
        if seed.parent is None:
            continue
        child, parent = by_name.get(seed.name), by_name.get(seed.parent)
        if child is not None and parent is not None and child.parent_skill_id is None:
            child.parent_skill_id = parent.id
            linked += 1

    await session.commit()
    log.info("skill taxonomy seeded", inserted=inserted, parents_linked=linked)
    return inserted
