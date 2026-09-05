"""Work history, education, project and certification schemas.

Read / Create / Update per type. The four are near-identical in shape but not in
fields, so they are written out rather than generated — a reader looking up what
a work experience accepts should find it here, not have to reconstruct it from a
factory.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EducationLevel, EmploymentType, WorkMode

MAX_HIGHLIGHTS = 20
MAX_HIGHLIGHT_CHARS = 500


class _EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Which upload produced this, or null when the user typed it in. Exposed so
    # the interface can say where a row came from rather than presenting a
    # parser's reading and the user's own words identically.
    source_version_id: uuid.UUID | None
    extraction_confidence: Decimal | None
    is_user_verified: bool
    created_at: datetime
    updated_at: datetime


def span_problem(
    start: date | None, end: date | None, is_current: bool
) -> tuple[str, str] | None:
    """The CHECK constraints on a dated entity, as (field, message) or None.

    A function rather than only a validator because the two write paths need it
    at different moments. A POST can be judged from the body alone; a PATCH
    cannot, since `exclude_unset` lets it carry one date and leave the other in
    the row — so the router re-runs this against the merged entity. Both call
    here so the rules cannot drift, which is exactly what had happened: only the
    create path was ever checked.
    """
    if start is not None and end is not None and end < start:
        return ("end_date", "The end date cannot be before the start date.")
    if is_current and end is not None:
        return ("end_date", "Something ongoing cannot also have an end date.")
    return None


def certification_span_problem(issued: date | None, expires: date | None) -> tuple[str, str] | None:
    """As span_problem, for the one entity whose dates are named differently."""
    if issued is not None and expires is not None and expires < issued:
        return ("expires_date", "The expiry date cannot be before the issue date.")
    return None


class _DatedBase(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def _check_dates(self):
        # Without this the database raises an IntegrityError, which the
        # catch-all turns into an opaque 500 instead of naming the field.
        problem = span_problem(self.start_date, self.end_date, self.is_current)
        if problem is not None:
            raise ValueError(problem[1])
        return self


def _clean_highlights(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        stripped = value.strip()[:MAX_HIGHLIGHT_CHARS]
        if stripped and stripped not in seen:
            seen.append(stripped)
    return seen[:MAX_HIGHLIGHTS]


# ------------------------------------------------------------ work experience


class WorkExperienceBase(_DatedBase):
    title: str = Field(min_length=1, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType | None = None
    work_mode: WorkMode | None = None
    description: str | None = Field(default=None, max_length=5000)
    highlights: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _tidy(self):
        object.__setattr__(self, "highlights", _clean_highlights(self.highlights))
        return self


class WorkExperienceCreate(WorkExperienceBase):
    pass


class WorkExperienceUpdate(BaseModel):
    """Every field optional — a PATCH sends only what changed.

    `exclude_unset` at the call site is what makes that work; without it an
    absent field arrives as None and a one-field edit wipes the rest.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType | None = None
    work_mode: WorkMode | None = None
    description: str | None = Field(default=None, max_length=5000)
    highlights: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class WorkExperienceRead(_EntityRead, WorkExperienceBase):
    pass


# ------------------------------------------------------------ education


class EducationBase(_DatedBase):
    institution: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    education_level: EducationLevel | None = None
    # Free text: "8.4 CGPA", "First Class" and "72%" are all real, and one
    # numeric column would either lose meaning or invent a conversion.
    grade: str | None = Field(default=None, max_length=50)


class EducationCreate(EducationBase):
    pass


class EducationUpdate(BaseModel):
    institution: str | None = Field(default=None, min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    education_level: EducationLevel | None = None
    grade: str | None = Field(default=None, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class EducationRead(_EntityRead, EducationBase):
    pass


# ------------------------------------------------------------ projects


class ProjectBase(_DatedBase):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    url: str | None = Field(default=None, max_length=1000)
    repository_url: str | None = Field(default=None, max_length=1000)
    highlights: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _tidy(self):
        object.__setattr__(self, "highlights", _clean_highlights(self.highlights))
        return self


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    url: str | None = Field(default=None, max_length=1000)
    repository_url: str | None = Field(default=None, max_length=1000)
    highlights: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class ProjectRead(_EntityRead, ProjectBase):
    pass


# ------------------------------------------------------------ certifications


class CertificationBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    credential_id: str | None = Field(default=None, max_length=200)
    credential_url: str | None = Field(default=None, max_length=1000)
    issued_date: date | None = None
    expires_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self):
        problem = certification_span_problem(self.issued_date, self.expires_date)
        if problem is not None:
            raise ValueError(problem[1])
        return self


class CertificationCreate(CertificationBase):
    pass


class CertificationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    credential_id: str | None = Field(default=None, max_length=200)
    credential_url: str | None = Field(default=None, max_length=1000)
    issued_date: date | None = None
    expires_date: date | None = None


class CertificationRead(_EntityRead, CertificationBase):
    pass


class CareerSummary(BaseModel):
    """Everything a resume produced, in one response.

    One request rather than four: the profile page renders all of these
    together, and four round trips to fill one screen is four chances for a
    partial render.
    """

    experiences: list[WorkExperienceRead]
    education: list[EducationRead]
    projects: list[ProjectRead]
    certifications: list[CertificationRead]
