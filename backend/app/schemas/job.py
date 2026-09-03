"""Job request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    JobSource,
    JobStatus,
    SalaryPeriod,
    SkillRequirement,
    WorkMode,
)

# Generous, because a real posting with a long benefits section runs long, and
# rejecting one for length is a worse failure than storing a few extra KB. The
# lower bound is enforced after cleaning, in the parser, where it can explain
# itself.
MAX_DESCRIPTION_CHARS = 60_000


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website: str | None = None
    industry: str | None = None


class JobSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: uuid.UUID
    name: str
    requirement: SkillRequirement
    min_years: Decimal | None = None
    extraction_confidence: Decimal | None = None


class JobSummary(BaseModel):
    """List-row shape. Deliberately excludes the description.

    A browse page of twenty jobs would otherwise ship twenty full postings —
    hundreds of kilobytes to render a list of titles.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company: CompanyRead | None = None
    location: str | None = None
    country_code: str | None = None
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    experience_level: ExperienceLevel | None = None
    min_years_experience: Decimal | None = None
    max_years_experience: Decimal | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    posted_at: datetime | None = None
    created_at: datetime
    skill_count: int = 0


class JobDetail(JobSummary):
    source: JobSource
    source_url: str | None = None
    status: JobStatus
    description_raw: str
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    min_education: EducationLevel | None = None
    expires_at: datetime | None = None
    skills: list[JobSkillRead] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int


class JobSubmitRequest(BaseModel):
    """Paste a posting (US-3.1 AC1).

    `title` and `company` are optional overrides. Supplied, they win over
    anything the parser reads out of the text — the person pasting knows what
    they pasted, and a heuristic that overrules them is infuriating.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "description": "Senior Backend Engineer\n\nRequirements\n- 5+ years of Python...",
                "title": "Senior Backend Engineer",
                "company": "Acme Inc",
                "source_url": "https://example.com/jobs/123",
            }
        }
    )

    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("title", "company", "source_url", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        # A cleared input posts "", which would otherwise override the parser
        # with an empty string and produce a job titled "".
        if isinstance(value, str) and not value.strip():
            return None
        return value


class JobSubmitResponse(BaseModel):
    job: JobDetail
    is_duplicate: bool = Field(
        description=(
            "True when this posting was already in the corpus; the existing job is returned."
        )
    )


class JobImportRecord(BaseModel):
    external_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    url: str | None = Field(default=None, max_length=1000)
    posted_at: datetime | None = None


class JobImportRequest(BaseModel):
    # Bounded so one request cannot hold a transaction open across a whole
    # dataset. A larger file is imported as several batches.
    records: list[JobImportRecord] = Field(min_length=1, max_length=500)


class ImportFailureRead(BaseModel):
    index: int
    external_id: str | None = None
    reason: str


class JobImportResponse(BaseModel):
    """A partial success is the normal outcome, not an error (US-3.3 AC2)."""

    created: int
    duplicates: int
    failed: list[ImportFailureRead]
    processed: int
