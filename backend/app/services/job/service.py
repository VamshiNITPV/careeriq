"""Job ingestion and browsing business logic (Epic 3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.models.enums import JobSource, ProcessingStatus
from app.models.job import Company, Job
from app.repositories.job import CompanyRepository, JobRepository, JobSkillRepository
from app.repositories.skill import SkillRepository
from app.services.job.normalization import normalize_company_name
from app.services.job.pipeline import ParsedJob, UnparseableJobError, parse_description
from app.services.resume.skill_extraction import build_matcher

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    job: Job
    is_duplicate: bool
    skills_written: int


@dataclass(frozen=True, slots=True)
class ImportFailure:
    index: int
    external_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    created: int
    duplicates: int
    failed: list[ImportFailure]

    @property
    def processed(self) -> int:
        return self.created + self.duplicates + len(self.failed)


class JobService:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        companies: CompanyRepository,
        job_skills: JobSkillRepository,
        skills: SkillRepository,
    ) -> None:
        self.jobs = jobs
        self.companies = companies
        self.job_skills = job_skills
        self.skills = skills

    async def submit(
        self,
        *,
        raw_text: str,
        user_id: uuid.UUID | None = None,
        title: str | None = None,
        company_name: str | None = None,
        source_url: str | None = None,
        source: JobSource = JobSource.USER_SUBMITTED,
        external_id: str | None = None,
        posted_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> SubmissionResult:
        """Parse a description and store it, unless it is one we already have.

        Two dedup checks, cheapest first:

        1. `(source, external_id)` — an import re-running over the same batch.
           This is what makes US-3.3 AC1 idempotent, and it is checked before
           parsing because parsing a row we are about to discard is waste.
        2. `content_hash` — the same posting pasted again, by anyone.

        A duplicate returns the canonical job and **creates no row** (US-3.2
        AC2). The `DUPLICATE` status and `canonical_job_id` column exist for the
        near-duplicate pass in Phase 6, where both rows are already in the
        corpus and one has to be demoted rather than never written.
        """
        if external_id is not None:
            existing = await self.jobs.find_by_external_id(source.value, external_id)
            if existing is not None:
                return SubmissionResult(job=existing, is_duplicate=True, skills_written=0)

        matcher = build_matcher(await self.skills.load_taxonomy())
        parsed = parse_description(
            raw_text=raw_text,
            matcher=matcher,
            title_hint=title,
            company_hint=company_name,
        )

        canonical = await self.jobs.find_by_content_hash(parsed.content_hash)
        if canonical is not None:
            log.info(
                "job submission matched an existing posting",
                job_id=str(canonical.id),
                content_hash=parsed.content_hash[:12],
            )
            return SubmissionResult(job=canonical, is_duplicate=True, skills_written=0)

        company = await self._resolve_company(parsed.company_name)

        job = Job(
            id=uuid7(),
            # The relationship, not company_id. Setting the id alone leaves
            # `job.company` unloaded, and `lazy="joined"` then fires a lazy load
            # when the response is serialised — outside any greenlet, which is
            # MissingGreenlet rather than an extra query.
            company=company,
            submitted_by_user_id=user_id,
            source=source,
            source_url=source_url,
            external_id=external_id,
            title=parsed.title,
            normalized_title=parsed.normalized_title or None,
            description_raw=raw_text,
            description_clean=parsed.description_clean,
            responsibilities=parsed.responsibilities,
            requirements=parsed.requirements,
            benefits=parsed.benefits,
            location=parsed.location,
            work_mode=parsed.work_mode,
            employment_type=parsed.employment_type,
            experience_level=parsed.experience_level,
            min_years_experience=parsed.min_years_experience,
            max_years_experience=parsed.max_years_experience,
            min_education=parsed.min_education,
            salary_min=parsed.salary_min,
            salary_max=parsed.salary_max,
            salary_currency=parsed.salary_currency,
            salary_period=parsed.salary_period,
            content_hash=parsed.content_hash,
            posted_at=posted_at,
            expires_at=expires_at,
            # Parsing already happened, synchronously, before this row existed.
            # The column stays because Phase 6 adds an embedding step that will
            # genuinely be asynchronous.
            parsing_status=ProcessingStatus.COMPLETE,
        )
        self.jobs.add(job)
        await self.jobs.flush()

        written = await self._write_skills(job.id, parsed)

        # created_at is a server default and the skills were written with a Core
        # INSERT, so neither is on the instance yet. Refreshing here loads both
        # inside the request's async context; leaving it to serialisation means
        # a lazy load with no greenlet to run it in.
        await self.jobs.refresh(job)

        log.info(
            "job ingested",
            job_id=str(job.id),
            source=source.value,
            skills=written,
            has_salary=parsed.salary_min is not None,
        )
        return SubmissionResult(job=job, is_duplicate=False, skills_written=written)

    async def _resolve_company(self, name: str | None) -> Company | None:
        """Find or create the employer.

        Keyed on the normalised name, so "Acme, Inc." and "ACME Inc" resolve to
        one row rather than fragmenting a company's postings — which would break
        the "same company" scoping that near-duplicate detection depends on.
        """
        if not name:
            return None
        normalized = normalize_company_name(name)
        if not normalized:
            return None

        existing = await self.companies.get_by_normalized_name(normalized)
        if existing is not None:
            return existing

        company = Company(id=uuid7(), name=name[:200], normalized_name=normalized[:200])
        self.companies.add(company)
        await self.companies.flush()
        return company

    async def _write_skills(self, job_id: uuid.UUID, parsed: ParsedJob) -> int:
        """Resolve extracted skill names to taxonomy ids and store them.

        Every canonical name here came *from* the taxonomy — the matcher only
        finds entries it was built from — so a lookup miss means the taxonomy
        changed underneath this request. Skipped rather than auto-created:
        creating skills from job text is Phase 5's curation job, not a side
        effect of one ingest.
        """
        if not parsed.skills:
            return 0

        resolved = await self.skills.get_by_names([m.canonical_name for m in parsed.skills])
        rows = [
            (resolved[m.canonical_name].id, m.requirement, m.confidence, m.min_years)
            for m in parsed.skills
            if m.canonical_name in resolved
        ]
        return await self.job_skills.replace_for_job(job_id=job_id, rows=rows)

    async def get_job(self, job_id: uuid.UUID) -> Job:
        job = await self.jobs.get(job_id)
        if job is None:
            raise ResourceNotFoundError("Job")
        return job

    async def list_jobs(self, **filters: object) -> tuple[list[Job], int]:
        return await self.jobs.list_active(**filters)  # type: ignore[arg-type]

    async def import_batch(self, records: list[dict[str, object]]) -> ImportResult:
        """Bulk-import a dataset (US-3.3).

        A failed record is collected and the batch continues (AC2). Aborting on
        the first bad row makes a 10,000-record import unusable: one malformed
        entry would mean nothing lands, and the operator has no way to find out
        which one without bisecting the file.

        Each record is flushed as it goes so a later failure cannot roll back
        earlier successes — but the transaction is still the request's, so the
        caller decides when it commits.
        """
        created = 0
        duplicates = 0
        failures: list[ImportFailure] = []

        for index, record in enumerate(records):
            external_id = record.get("external_id")
            try:
                description = record.get("description")
                if not isinstance(description, str) or not description.strip():
                    raise ValidationError("Record has no description.")

                result = await self.submit(
                    raw_text=description,
                    title=_optional_str(record.get("title")),
                    company_name=_optional_str(record.get("company")),
                    source_url=_optional_str(record.get("url")),
                    source=JobSource.DATASET_IMPORT,
                    external_id=_optional_str(external_id),
                    posted_at=_optional_datetime(record.get("posted_at")),
                )
                if result.is_duplicate:
                    duplicates += 1
                else:
                    created += 1
            except (UnparseableJobError, ValidationError) as exc:
                failures.append(
                    ImportFailure(
                        index=index,
                        external_id=_optional_str(external_id),
                        reason=getattr(exc, "message", str(exc)),
                    )
                )
            except Exception as exc:
                # A record that fails in an unexpected way must not take the
                # batch with it. Logged with a stack trace; reported to the
                # operator without internals.
                log.exception("job import record failed", index=index)
                failures.append(
                    ImportFailure(
                        index=index,
                        external_id=_optional_str(external_id),
                        reason=f"Unexpected error: {type(exc).__name__}",
                    )
                )

        log.info(
            "job import finished",
            created=created,
            duplicates=duplicates,
            failed=len(failures),
        )
        return ImportResult(created=created, duplicates=duplicates, failed=failures)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
