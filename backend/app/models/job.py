"""Companies, jobs and job skill requirements (database.md section 3.3).

The corpus every later phase depends on: ranking scores a candidate against
these rows, `demand_score` is computed by counting them, and gap analysis asks
which skills they require. Parsing quality here sets the ceiling on all of it.

`description_raw` is never mutated. Re-parsing with a better extractor has to be
possible without the user re-pasting anything, which means the original text is
the source of truth and everything else on the row is derived.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobSource,
    JobStatus,
    ProcessingStatus,
    SalaryPeriod,
    SkillRequirement,
    WorkMode,
)


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An employer.

    A real table rather than a string on `jobs`, because the same employer posts
    repeatedly and near-duplicate detection is scoped to "same company or
    similar title" (ml.md section 5). Without a shared identity that scoping has
    nothing to key on, and every new job would have to be compared against the
    entire corpus.
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Lowercased with punctuation and legal suffixes stripped, so "Acme, Inc."
    # and "ACME Inc" resolve to one row. Unique, and the only lookup key.
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    headquarters: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "jobs"

    # RESTRICT: deleting a company that still has postings would orphan them.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True
    )
    # SET NULL, not CASCADE: a job someone pasted stays in the corpus after they
    # delete their account. It is a fact about the market, not their data.
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    source: Mapped[JobSource] = mapped_column(_pg_enum(JobSource, "job_source"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The upstream dataset's own id. Unique per source, which is the whole
    # mechanism behind idempotent import (US-3.3 AC1).
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # "Sr. Software Engineer II" → "software engineer". Grouping key for
    # analytics and the trigram scope for near-duplicate comparison.
    normalized_title: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Never mutated. Everything else on this row is derived from it, so a better
    # parser can be re-run without asking anyone to paste the posting again.
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    # Whitespace-collapsed and boilerplate-stripped. What gets hashed for exact
    # dedup, and what gets embedded in Phase 6.
    description_clean: Mapped[str | None] = mapped_column(Text, nullable=True)

    responsibilities: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    requirements: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    benefits: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )

    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    work_mode: Mapped[WorkMode | None] = mapped_column(
        _pg_enum(WorkMode, "work_mode"), nullable=True
    )
    employment_type: Mapped[EmploymentType | None] = mapped_column(
        _pg_enum(EmploymentType, "employment_type"), nullable=True
    )
    experience_level: Mapped[ExperienceLevel | None] = mapped_column(
        _pg_enum(ExperienceLevel, "experience_level"), nullable=True
    )
    min_years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    max_years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    min_education: Mapped[EducationLevel | None] = mapped_column(
        _pg_enum(EducationLevel, "education_level"), nullable=True
    )

    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_period: Mapped[SalaryPeriod | None] = mapped_column(
        _pg_enum(SalaryPeriod, "salary_period"), nullable=True
    )

    # SHA-256 of description_clean. Stage one of dedup: an index lookup that
    # catches exact re-posts before any expensive comparison (US-3.2 AC1).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set when status is DUPLICATE. Points at the survivor so a reference to the
    # loser can still be resolved to the real posting (US-3.2 AC2).
    canonical_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL", use_alter=True, name="fk_jobs_canonical_job_id"),
        nullable=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        _pg_enum(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.ACTIVE,
        server_default=text("'ACTIVE'::job_status"),
    )

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parsing_status: Mapped[ProcessingStatus] = mapped_column(
        _pg_enum(ProcessingStatus, "processing_status"),
        nullable=False,
        default=ProcessingStatus.PENDING,
        server_default=text("'PENDING'::processing_status"),
    )
    parsing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped[Company | None] = relationship(lazy="joined")
    # foreign_keys is required: canonical_job_id is a second FK from this table
    # to itself, and without it SQLAlchemy cannot tell which path the
    # relationship follows.
    skills: Mapped[list[JobSkill]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="JobSkill.job_id",
    )

    __table_args__ = (
        # Partial: the ranking query only ever reads live postings, so the index
        # covers only those and stays small as duplicates accumulate.
        Index(
            "ix_jobs_active",
            "status",
            text("posted_at DESC"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_jobs_content_hash", "content_hash"),
        Index(
            "ix_jobs_title_trgm",
            "normalized_title",
            postgresql_using="gin",
            postgresql_ops={"normalized_title": "gin_trgm_ops"},
        ),
        Index("ix_jobs_location", "country_code", "location"),
        Index("ix_jobs_company", "company_id"),
        # What makes re-running an import create nothing new (US-3.3 AC1).
        # Partial, because a user paste has no external id and any number of
        # those may exist.
        Index(
            "ux_jobs_external",
            "source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="salary_range_ordered",
        ),
        CheckConstraint(
            "min_years_experience IS NULL OR max_years_experience IS NULL "
            "OR max_years_experience >= min_years_experience",
            name="years_range_ordered",
        ),
        CheckConstraint(
            "salary_currency IS NULL OR char_length(salary_currency) = 3",
            name="currency_is_iso4217",
        ),
        CheckConstraint(
            "country_code IS NULL OR char_length(country_code) = 2",
            name="country_is_iso3166",
        ),
        # A duplicate must say what it duplicates, and a live job must not claim
        # to duplicate anything. Enforced here because a DUPLICATE with a null
        # canonical is a row nothing can resolve.
        CheckConstraint(
            "(status = 'DUPLICATE') = (canonical_job_id IS NOT NULL)",
            name="duplicate_has_canonical",
        ),
        CheckConstraint("canonical_job_id IS NULL OR canonical_job_id <> id", name="not_self_dupe"),
    )


class JobSkill(Base, UUIDPrimaryKeyMixin):
    """A skill one job asks for, and how badly.

    Its own table rather than two arrays on `jobs`, for the reason database.md
    section 3.2 gives: skills are shared entities with their own identity, so
    "in what fraction of active jobs is this REQUIRED?" has to be an indexed
    query rather than a scan over arrays.
    """

    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: tidying the taxonomy must not silently change what a job asks
    # for.
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )

    requirement: Mapped[SkillRequirement] = mapped_column(
        _pg_enum(SkillRequirement, "skill_requirement"), nullable=False
    )
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    job: Mapped[Job] = relationship(back_populates="skills", foreign_keys=[job_id])
    skill: Mapped[Skill] = relationship(lazy="joined")  # noqa: F821

    __table_args__ = (
        Index("ux_job_skills", "job_id", "skill_id", unique=True),
        # Powers demand_score and gap severity (US-5.1 AC2).
        Index("ix_job_skills_skill", "skill_id", "requirement"),
        CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_is_fraction",
        ),
        CheckConstraint("min_years IS NULL OR min_years >= 0", name="min_years_non_negative"),
    )
