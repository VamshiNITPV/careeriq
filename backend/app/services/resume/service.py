"""Resume upload and management business logic."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.integrations.storage import ObjectStorage, build_storage_key
from app.models.enums import ProcessingStatus
from app.models.resume import Resume, ResumeVersion
from app.repositories.resume import ResumeRepository, ResumeVersionRepository
from app.repositories.skill import CandidateSkillRepository
from app.services.file_validation import ValidatedUpload

log = get_logger(__name__)

# A cap on resumes per user. Not a business rule so much as a guard: without
# one, an automated client can fill object storage indefinitely, and there is no
# rate limiting until Phase 10.
MAX_RESUMES_PER_USER = 20


class ResumeService:
    def __init__(
        self,
        *,
        resumes: ResumeRepository,
        versions: ResumeVersionRepository,
        storage: ObjectStorage,
        candidate_skills: CandidateSkillRepository | None = None,
    ) -> None:
        self.resumes = resumes
        self.versions = versions
        self.storage = storage
        # Optional so the service can still be constructed for upload-only use
        # without dragging in a repository it does not need.
        self.candidate_skills = candidate_skills

    async def upload(
        self,
        *,
        user_id: uuid.UUID,
        upload: ValidatedUpload,
        title: str | None = None,
        resume_id: uuid.UUID | None = None,
    ) -> tuple[Resume, ResumeVersion, bool]:
        """Store a file and create a version for it.

        Returns `(resume, version, is_duplicate)`. A duplicate is an identical
        file this user already uploaded; the version is created but the pipeline
        is skipped, because reprocessing identical bytes can only produce the
        result we already have.
        """
        content_hash = hashlib.sha256(upload.content).hexdigest()

        if resume_id is not None:
            resume = await self.resumes.get_owned(resume_id, user_id)
            if resume is None:
                raise ResourceNotFoundError("Resume")
        else:
            if await self.resumes.count_for_user(user_id) >= MAX_RESUMES_PER_USER:
                raise ConflictError(
                    f"You can store up to {MAX_RESUMES_PER_USER} resumes. "
                    "Delete one before uploading another.",
                    code="RESUME_LIMIT_REACHED",
                )
            resume = await self._create_resume(
                user_id=user_id, title=title or upload.original_filename
            )

        duplicate = await self.versions.find_by_content_hash(user_id, content_hash)

        # Key is generated, never derived from the client filename (ADR-014).
        storage_key = build_storage_key(user_id=str(user_id), extension=upload.extension)
        await self.storage.put(storage_key, upload.content, content_type=upload.document_type.value)

        version = ResumeVersion(
            id=uuid7(),
            resume_id=resume.id,
            version_number=await self.versions.next_version_number(resume.id),
            storage_key=storage_key,
            original_filename=upload.original_filename,
            mime_type=upload.document_type.value,
            file_size_bytes=upload.size_bytes,
            content_hash=content_hash,
            processing_status=ProcessingStatus.PENDING,
        )
        self.versions.add(version)
        await self.versions.flush()

        if duplicate is not None and duplicate.processing_status is ProcessingStatus.COMPLETE:
            # Copy the previous result across rather than re-running the
            # pipeline on bytes we have already parsed.
            version.raw_text = duplicate.raw_text
            version.parsed_sections = duplicate.parsed_sections
            version.parsed_entities = duplicate.parsed_entities
            version.processing_status = ProcessingStatus.COMPLETE
            version.processed_at = datetime.now(UTC)
            await self.resumes.set_current_version(resume.id, version.id)
            await self.versions.flush()
            log.info(
                "resume upload matched an existing file; reused parse result",
                user_id=str(user_id),
                version_id=str(version.id),
            )
            return resume, version, True

        # Commit before returning, because the caller hands this version's id to
        # a background worker that runs on its **own connection**. Until the
        # transaction commits, that row does not exist as far as any other
        # connection is concerned, so the worker starts, finds nothing, and the
        # upload silently never parses.
        #
        # This is the second deliberate exception to "the request owns the
        # transaction" (see RefreshTokenRepository usage in AuthService.refresh
        # for the first). Handing work to something outside the transaction
        # requires the work to be visible outside the transaction.
        await self.versions.commit()

        log.info(
            "resume uploaded",
            user_id=str(user_id),
            resume_id=str(resume.id),
            version_id=str(version.id),
            size_bytes=upload.size_bytes,
        )
        return resume, version, False

    async def _create_resume(self, *, user_id: uuid.UUID, title: str) -> Resume:
        # The first resume becomes primary automatically: requiring an extra
        # click to mark the only resume as primary is pure friction.
        is_first = await self.resumes.count_for_user(user_id) == 0
        resume = Resume(id=uuid7(), user_id=user_id, title=title[:200], is_primary=is_first)
        self.resumes.add(resume)
        await self.resumes.flush()
        return resume

    async def list_resumes(self, user_id: uuid.UUID) -> list[Resume]:
        return await self.resumes.list_for_user(user_id)

    async def get_resume(self, *, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume:
        resume = await self.resumes.get_owned(resume_id, user_id)
        if resume is None:
            # 404, not 403 — confirming the row exists would let an attacker
            # enumerate ids (US-1.5 AC1).
            raise ResourceNotFoundError("Resume")
        return resume

    async def get_version(self, *, version_id: uuid.UUID, user_id: uuid.UUID) -> ResumeVersion:
        version = await self.versions.get_owned(version_id, user_id)
        if version is None:
            raise ResourceNotFoundError("Resume version")
        return version

    async def rename(self, *, resume_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Resume:
        resume = await self.get_resume(resume_id=resume_id, user_id=user_id)
        resume.title = title[:200]
        return resume

    async def set_primary(self, *, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume:
        resume = await self.get_resume(resume_id=resume_id, user_id=user_id)
        # Must clear first: a partial unique index allows only one primary per
        # user, so setting the new one first would violate it.
        await self.resumes.clear_primary(user_id)
        await self.resumes.flush()
        resume.is_primary = True
        return resume

    async def delete(self, *, resume_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Soft delete the resume and drop the skills it produced.

        The stored files and version rows are deliberately left in place.
        Applications reference the resume version they were submitted with, and
        destroying that record would quietly corrupt the analytics that depend
        on it (database.md section 3.7). Reclaiming orphaned objects is a
        Phase 10 job.

        The extracted skills, however, do go. They are derived from the
        document, so leaving them behind means a deleted resume leaves claims
        on the profile that the user can no longer trace to anything — which is
        exactly what it looks like when it is wrong.

        Skills the user added or corrected by hand survive: those are their own
        claims rather than a derivation, and the `is_user_verified` flag is what
        distinguishes them.
        """
        resume = await self.get_resume(resume_id=resume_id, user_id=user_id)
        resume.deleted_at = datetime.now(UTC)
        resume.is_primary = False

        removed = 0
        if self.candidate_skills is not None:
            removed = await self.candidate_skills.delete_extracted_for_resume(
                user_id=user_id, resume_id=resume_id
            )

        log.info(
            "resume deleted",
            user_id=str(user_id),
            resume_id=str(resume_id),
            extracted_skills_removed=removed,
        )

    async def download(
        self, *, version_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[bytes, str, str]:
        """Return `(content, filename, mime_type)` for an owned version."""
        version = await self.get_version(version_id=version_id, user_id=user_id)
        content = await self.storage.get(version.storage_key)
        return content, version.original_filename, version.mime_type
