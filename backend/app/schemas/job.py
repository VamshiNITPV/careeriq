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
from app.schemas.urls import normalize_url

# Generous, because a real posting with a long benefits section runs long, and
# rejecting one for length is a worse failure than storing a few extra KB. The
# lower bound is enforced after cleaning, in the parser, where it can explain
# itself.
MAX_DESCRIPTION_CHARS = 60_000

# Wider than the profile's MAX_URL because application links are genuinely long:
# Greenhouse, Workday and Lever carry gh_jid, utm_* and referral tokens, and 500
# is reachable. The column is TEXT with no bound of its own, so this is purely a
# request-size guard.
MAX_JOB_URL = 1000


def _application_link(value: object) -> object:
    """Normalise and validate an application link.

    One function so the submit path and the add-a-link PATCH cannot drift; both
    end up in the same `href`. `required=True` because both fields are.
    """
    return normalize_url(value, max_length=MAX_JOB_URL, required=True)


def _optional_application_link(value: object) -> object:
    """The same rules, but a bad link costs the link rather than the record.

    Imports need both halves of this. Without any normalisation the importer is
    a route into an `href` that skips schemas/urls.py entirely — the exact hole
    the fetch path calls normalize_url explicitly to close — and it can store a
    value that is not a link, which the interface then shows as "no application
    link" while refusing to let anyone repair it.

    But raising here would reject the whole batch on one bad URL: this is a
    field validator on a list item, so the 422 kills every other record with it,
    and US-3.3 AC2 says a failed record must not abort the batch. Dropping the
    unusable link keeps the posting — whose skills and salary are what the
    ranking actually consumes — and the detail page then offers to add one.
    """
    try:
        return normalize_url(value, max_length=MAX_JOB_URL)
    except ValueError:
        return None


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
    # Required: this is the link the interface offers as "Apply for this job",
    # and a posting someone pasted always came from a page. Note that the
    # importer deliberately does NOT require one — see JobImportRecord.url.
    source_url: str = Field(max_length=MAX_JOB_URL)

    # source_url is deliberately NOT in this list. Blanking it to None would
    # reach Pydantic as a missing str and surface as "Input should be a valid
    # string"; _apply_link says what is actually wrong instead.
    @field_validator("title", "company", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        # A cleared input posts "", which would otherwise override the parser
        # with an empty string and produce a job titled "".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    _apply_link = field_validator("source_url", mode="before")(_application_link)


class JobSubmitResponse(BaseModel):
    job: JobDetail
    is_duplicate: bool = Field(
        description=(
            "True when this posting was already in the corpus; the existing job is returned."
        )
    )


class JobApplicationLinkUpdate(BaseModel):
    """Attach an application link to a job that has none."""

    source_url: str = Field(max_length=MAX_JOB_URL)

    _apply_link = field_validator("source_url", mode="before")(_application_link)


class JobImportRecord(BaseModel):
    external_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    # Optional, unlike JobSubmitRequest.source_url, and that divergence is
    # deliberate rather than an oversight. A dataset row's value to the ranking
    # formula — skills, salary, requirements — does not depend on a link, and
    # failing a whole record over a missing one makes an operator bisect the
    # file for a non-reason. A linkless imported row is exactly what the
    # "add the application link" control on the detail page exists for.
    url: str | None = Field(default=None, max_length=MAX_JOB_URL)
    # Structured metadata beats parsing it back out of prose. country_code has
    # no parser at all, so without this the documented `GET /jobs?country_code=`
    # filter matches nothing.
    location: str | None = Field(default=None, max_length=200)
    country_code: str | None = Field(default=None, max_length=2)
    posted_at: datetime | None = None

    _link = field_validator("url", mode="before")(_optional_application_link)


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


class JobFetchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    country: str = Field(default="in", min_length=2, max_length=2)
    # Defaults to one, and that is the whole answer to an accidental
    # double-fire: on a free tier measured in a few hundred calls a month, a
    # double-click must cost one request rather than five. Five is the ceiling
    # and choosing it is a deliberate act. api.md section 1.8 specifies an
    # Idempotency-Key for this class of endpoint; nothing implements one yet
    # (Redis is configured but unused), so this plus (source, external_id)
    # dedup is the interim — a repeat spends quota but creates no rows.
    max_pages: int = Field(default=1, ge=1, le=5)


class JobFetchResponse(BaseModel):
    """Deliberately the same report shape as JobImportResponse.

    Standalone rather than a subclass because that model's docstring is US-3.3's
    contract and should stay that, but `failed` is the identical type: an
    operator reading either one is asking the same question.
    """

    provider: str
    created: int
    duplicates: int
    failed: list[ImportFailureRead]
    processed: int
    pages_fetched: int
    postings_seen: int
    stopped_early: bool
    stop_reason: str | None = None
    #: Surfaced in the response, not just the log: "what did that cost me" is a
    #: question asked at the moment the button is pressed.
    quota_remaining: int | None = None
