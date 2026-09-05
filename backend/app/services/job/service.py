"""Job ingestion and browsing business logic (Epic 3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError, ValidationError
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


#: PostgreSQL SQLSTATE for a unique violation. Anything else reaching an
#: IntegrityError — a CHECK violation from an impossible salary range, a foreign
#: key problem — is a genuine failure, not a duplicate.
_UNIQUE_VIOLATION = "23505"


def is_duplicate_row(exc: IntegrityError) -> bool:
    """Whether an IntegrityError means "this row already exists".

    Reporting every integrity error as a duplicate tells an operator "you
    already have these" when in fact nothing was written and something else is
    wrong — the one reading of the report that stops them investigating.
    """
    return getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION


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
        # Structured metadata a caller already holds, applied with the same
        # precedence as title/company: supplied wins over parsed. A jobs API
        # gives these as fields, while find_location only matches a labelled
        # "Location:" line in the header that API prose never has — and
        # country_code has no parser at all, so it is hint-only and is NULL on
        # every row written before this existed.
        location: str | None = None,
        country_code: str | None = None,
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
            # A duplicate submission is the cheapest moment the corpus ever gets
            # to improve. The submitter had to give a link, and the row we are
            # about to hand back may have none — an imported one usually does
            # not. Without this the user lands on a detail page saying "no
            # application link was given" holding the link they just typed.
            #
            # Through the repository, not `canonical.source_url = ...`. A
            # read-then-write here is the very race attach_source_url exists to
            # close, and two people submitting the same posting at once is
            # exactly when it would bite. The `is not None` guard matters: the
            # importer reaches this same code with no link at all.
            if source_url is not None and await self.jobs.attach_source_url(
                job_id=canonical.id, source_url=source_url
            ):
                await self.jobs.refresh(canonical)
                log.info(
                    "job application link added by a duplicate submission",
                    job_id=str(canonical.id),
                    actor_user_id=str(user_id) if user_id else None,
                    host=urlsplit(source_url).hostname,
                )
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
            location=location or parsed.location,
            country_code=_country_code(country_code),
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

    async def set_application_link(
        self, *, job_id: uuid.UUID, source_url: str, actor_user_id: uuid.UUID
    ) -> Job:
        """Attach an application link to a job that has none.

        Set-only-when-null, and deliberately not general editing. The corpus is
        shared, so this is the one write path where one user changes what every
        other user sees — behind a button reading "Apply for this job", in the
        context where people hand over a CV and a phone number. Refusing to
        replace a link that is already there is most of what keeps that safe: a
        correct link can never be swapped for a hostile one.

        The actor is logged because nothing else records who did this. Be clear
        about the limit of that: the structured log is the *only* record, there
        is no in-app audit trail, and undoing one person's link means editing
        the database by hand.
        """
        if not await self.jobs.attach_source_url(job_id=job_id, source_url=source_url):
            # Zero rows updated means one of two things, and they are different
            # answers to the caller: the job is gone, or somebody got there
            # first. get_job raises ResourceNotFoundError for the former.
            await self.get_job(job_id)
            raise ConflictError("This job already has an application link.")

        job = await self.get_job(job_id)
        # Not defensive. That was a Core UPDATE, so `updated_at` — which
        # PostgreSQL recomputes via onupdate — is expired on the loaded
        # instance, and reading it during serialisation is a MissingGreenlet
        # rather than an extra query. Without this the response can also echo
        # back the pre-update source_url for a write that succeeded.
        await self.jobs.refresh(job)

        log.info(
            "job application link added",
            job_id=str(job_id),
            actor_user_id=str(actor_user_id),
            # Host, not the whole URL: the link may carry a referral token, and
            # the host is what an abuse report actually needs.
            host=urlsplit(source_url).hostname,
        )
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

                # A savepoint per record, because the try/except alone does not
                # deliver AC2. It catches a record that fails *before* the
                # flush — too short to parse — but a failure *inside* it (an
                # over-long external_id, a check violation, a unique race)
                # leaves the session unusable, so every later record dies of
                # PendingRollbackError and the request then 500s at commit.
                async with self.jobs.savepoint():
                    result = await self.submit(
                        raw_text=description,
                        title=_optional_str(record.get("title")),
                        company_name=_optional_str(record.get("company")),
                        source_url=_optional_str(record.get("url")),
                        location=_optional_str(record.get("location")),
                        country_code=_optional_str(record.get("country_code")),
                        source=JobSource.DATASET_IMPORT,
                        external_id=_optional_str(external_id),
                        posted_at=_optional_datetime(record.get("posted_at")),
                    )
                if result.is_duplicate:
                    duplicates += 1
                else:
                    created += 1
            except IntegrityError as exc:
                # A unique violation means two imports raced to insert the same
                # (source, external_id): the savepoint rolled this one back and
                # the other's row is canonical, so it is a duplicate. Any other
                # integrity error is a real failure and must say so.
                if is_duplicate_row(exc):
                    duplicates += 1
                else:
                    log.exception("job import record violated a constraint", index=index)
                    failures.append(
                        ImportFailure(
                            index=index,
                            external_id=_optional_str(external_id),
                            reason=f"Rejected by the database: {_constraint_of(exc)}",
                        )
                    )
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


def _constraint_of(exc: IntegrityError) -> str:
    """The constraint an integrity error names, for a report an operator can act on."""
    return getattr(exc.orig, "constraint_name", None) or "constraint violated"


def _country_code(value: str | None) -> str | None:
    """An ISO-3166 alpha-2 code, or nothing.

    Guarded here rather than trusted, because the value arrives from a third
    party and `country_code_is_iso3166` is a CHECK constraint — a bad one is an
    IntegrityError mid-flush, which poisons the session for the rest of the
    batch. Dropping an unrecognisable code costs one filterable field; letting
    it through costs the batch.
    """
    if value is None:
        return None
    candidate = value.strip().upper()
    return candidate if len(candidate) == 2 and candidate.isalpha() else None


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
