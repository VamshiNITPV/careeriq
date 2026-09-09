"""Turn the backlog into stored vectors.

backlog query -> build document -> compare hash -> embed -> upsert.

Session-injectable rather than opening its own, following the resume pipeline:
the tests run inside a transaction that is rolled back, and a service that
reached for its own session would not see the rows under test.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.models.career import EducationRecord, Project, WorkExperience
from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume, ResumeVersion
from app.models.skill import CandidateSkill
from app.repositories.embedding import CandidateEmbeddingRepository, JobEmbeddingRepository
from app.services.embedding.documents import (
    build_candidate_document,
    build_job_document,
    document_hash,
    is_embeddable,
)

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IndexResult:
    """What one pass did. `skipped` is the number that proves the hash works."""

    considered: int
    embedded: int
    skipped: int
    too_short: int


class DimensionMismatchError(RuntimeError):
    """The provider's width disagrees with the column's.

    Raised before anything is written. pgvector fixes the dimension in the
    column type, so a mismatched vector cannot be stored at all — failing here,
    once, with the two numbers in the message beats a per-row database error
    that names neither.
    """


def _check_dimensions(provider: EmbeddingProvider) -> None:
    expected = get_settings().embedding_dimensions
    if provider.dimensions != expected:
        raise DimensionMismatchError(
            f"{provider.model_name} produces {provider.dimensions}-dim vectors, "
            f"but the column is {expected}-dim. Changing model width is a migration."
        )


async def index_jobs(
    *, session: AsyncSession, provider: EmbeddingProvider, batch_size: int
) -> IndexResult:
    _check_dimensions(provider)
    repository = JobEmbeddingRepository(session)

    job_ids = await repository.backlog(
        model_name=provider.model_name,
        model_version=provider.model_version,
        limit=batch_size,
    )
    if not job_ids:
        return IndexResult(0, 0, 0, 0)

    jobs = list((await session.scalars(select(Job).where(Job.id.in_(job_ids)))).unique().all())

    pending: list[tuple[Job, str, str]] = []
    too_short = 0
    skipped = 0
    for job in jobs:
        document = build_job_document(job)
        if not is_embeddable(document):
            # Nothing is written. A near-empty document produces a vector that
            # is mostly noise, and it would sit in the corpus looking like a
            # plausible neighbour for anything at all.
            too_short += 1
            continue

        digest = document_hash(document)
        stored = await repository.hash_for(
            job.id, model_name=provider.model_name, model_version=provider.model_version
        )
        if stored == digest:
            # The backlog query is deliberately over-eager; this is where that
            # is corrected, before any model time is spent.
            skipped += 1
            continue

        pending.append((job, document, digest))

    if pending:
        vectors = await provider.embed([document for _, document, _ in pending])
        for (job, _, digest), vector in zip(pending, vectors, strict=True):
            await repository.upsert(
                job_id=job.id,
                embedding=vector,
                model_name=provider.model_name,
                model_version=provider.model_version,
                dimensions=provider.dimensions,
                source_text_hash=digest,
            )

    return IndexResult(len(job_ids), len(pending), skipped, too_short)


async def _candidate_document(session: AsyncSession, version_id: uuid.UUID) -> str | None:
    """Build one candidate document from the user's live profile and career rows."""
    version = await session.scalar(select(ResumeVersion).where(ResumeVersion.id == version_id))
    if version is None:
        return None
    resume = await session.scalar(select(Resume).where(Resume.id == version.resume_id))
    if resume is None:
        return None

    user_id = resume.user_id
    profile = await session.scalar(select(Profile).where(Profile.user_id == user_id))
    skills = list(
        (await session.scalars(select(CandidateSkill).where(CandidateSkill.user_id == user_id)))
        .unique()
        .all()
    )
    experiences = list(
        (
            await session.scalars(
                select(WorkExperience)
                .where(WorkExperience.user_id == user_id)
                .order_by(WorkExperience.start_date.desc().nullslast())
            )
        ).all()
    )
    education = list(
        (
            await session.scalars(select(EducationRecord).where(EducationRecord.user_id == user_id))
        ).all()
    )
    projects = list(
        (await session.scalars(select(Project).where(Project.user_id == user_id))).all()
    )

    total_years: Decimal | None = profile.years_of_experience if profile is not None else None

    return build_candidate_document(
        profile=profile,
        skills=skills,
        experiences=experiences,
        education=education,
        projects=projects,
        total_years=total_years,
    )


async def index_candidates(
    *, session: AsyncSession, provider: EmbeddingProvider, batch_size: int
) -> IndexResult:
    _check_dimensions(provider)
    repository = CandidateEmbeddingRepository(session)

    version_ids = await repository.backlog(limit=batch_size)
    if not version_ids:
        return IndexResult(0, 0, 0, 0)

    pending: list[tuple[uuid.UUID, str, str]] = []
    too_short = 0
    skipped = 0
    for version_id in version_ids:
        document = await _candidate_document(session, version_id)
        if document is None or not is_embeddable(document):
            too_short += 1
            continue

        digest = document_hash(document)
        stored = await repository.hash_for(
            version_id, model_name=provider.model_name, model_version=provider.model_version
        )
        if stored == digest:
            skipped += 1
            continue

        pending.append((version_id, document, digest))

    if pending:
        vectors = await provider.embed([document for _, document, _ in pending])
        for (version_id, _, digest), vector in zip(pending, vectors, strict=True):
            await repository.upsert(
                resume_version_id=version_id,
                embedding=vector,
                model_name=provider.model_name,
                model_version=provider.model_version,
                dimensions=provider.dimensions,
                source_text_hash=digest,
            )

    return IndexResult(len(version_ids), len(pending), skipped, too_short)


async def run_once(
    *, session: AsyncSession, provider: EmbeddingProvider, batch_size: int
) -> tuple[IndexResult, IndexResult]:
    """One pass over both backlogs. Returns (jobs, candidates)."""
    try:
        jobs = await index_jobs(session=session, provider=provider, batch_size=batch_size)
        candidates = await index_candidates(
            session=session, provider=provider, batch_size=batch_size
        )
    except EmbeddingProviderError:
        # Collapsed by the provider on purpose: every caller makes the same
        # decision on it, which is to leave the backlog alone and try again.
        log.exception("embedding failed; backlog is unchanged")
        raise

    return jobs, candidates
