"""Profile request and response schemas.

Every rule here mirrors a database constraint from models/profile.py — four CHECK
constraints and several length-bounded columns. That duplication is deliberate:
anything this layer misses reaches Postgres, raises an IntegrityError or
DataError, and is caught by the catch-all handler in main.py as an opaque 500.
A validation failure should be a 422 that names the field.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.models.enums import EducationLevel, EmploymentType, ExperienceLevel, WorkMode

# Bounds matching the column definitions.
MAX_NAME = 200
MAX_HEADLINE = 300
MAX_LOCATION = 200
MAX_PHONE = 50
MAX_SUMMARY = 5000
MAX_URL = 500
# A preference list long enough for any real answer, short enough that nobody
# can push a megabyte of text into an unbounded array.
MAX_LIST_ITEMS = 20


def _blank_to_none(value: Any) -> Any:
    """Treat an empty or whitespace-only string as absent.

    A cleared HTML input posts `""`, not null. Storing that would leave two
    representations of "empty" in the column, and the resume autofill's
    "is this field empty?" check would have to know about both.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _normalize_url(value: Any) -> Any:
    """Validate a URL and return it as a plain string.

    Deliberately not typed as `HttpUrl` on the field. Pydantic normalises that
    type on serialisation — lowercasing the host, appending a trailing slash —
    so the value echoed back would differ from what the user typed, and the
    input would appear to change itself on save.

    A missing scheme is added rather than rejected: people write
    "linkedin.com/in/priya", and 422-ing that is pedantry.
    """
    if value is None or not isinstance(value, str):
        return value

    candidate = value.strip()
    if not candidate:
        return None
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    try:
        AnyHttpUrl(candidate)
    except ValidationError as exc:
        raise ValueError("Enter a valid URL.") from exc

    if len(candidate) > MAX_URL:
        raise ValueError(f"URL must be at most {MAX_URL} characters.")
    return candidate


def _clean_list(values: list[str]) -> list[str]:
    """Strip, drop empties, and de-duplicate while preserving order.

    Order is preserved because these are user-ordered preferences — a target
    role list reordered on save looks like a bug.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        item = raw.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


class ProfilePersonalUpdate(BaseModel):
    """PATCH body. Every field optional; only what is sent is changed.

    The handler must use `model_dump(exclude_unset=True)`. Without it, absent
    fields arrive as None and a one-field edit silently clears the other eight.
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"full_name": "Priya Sharma", "headline": "Backend Engineer"}}
    )

    full_name: str | None = Field(default=None, max_length=MAX_NAME)
    headline: str | None = Field(default=None, max_length=MAX_HEADLINE)
    location: str | None = Field(default=None, max_length=MAX_LOCATION)
    # ck_profiles_country_is_iso3166 requires exactly two characters.
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    phone: str | None = Field(default=None, max_length=MAX_PHONE)
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY)
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None

    _blank = field_validator(
        "full_name",
        "headline",
        "location",
        "country_code",
        "phone",
        "summary",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        mode="before",
    )(_blank_to_none)

    @field_validator("linkedin_url", "github_url", "portfolio_url", mode="before")
    @classmethod
    def _urls(cls, value: Any) -> Any:
        return _normalize_url(value)

    @field_validator("country_code")
    @classmethod
    def _upper_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("full_name", "headline", "location", "phone", "summary")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class PreferencesReplace(BaseModel):
    """PUT body — replaces the preference set wholesale.

    PUT rather than PATCH because these are arrays: with PATCH, "set this to
    empty" and "leave this alone" are the same absent-or-empty payload, and
    telling them apart needs `model_fields_set` inspection at every call site.
    Replace-wholesale has exactly one meaning, and it matches how a settings
    form actually submits (docs/api.md section 2.2).
    """

    target_roles: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    preferred_locations: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    preferred_work_modes: list[WorkMode] = Field(default_factory=list)
    preferred_employment_types: list[EmploymentType] = Field(default_factory=list)
    min_salary_expectation: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    # ck_profiles_currency_is_iso4217 requires exactly three characters.
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    open_to_relocation: bool = False

    @field_validator("target_roles", "preferred_locations")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        return _clean_list(values)

    @field_validator("preferred_work_modes", "preferred_employment_types")
    @classmethod
    def _dedupe_enums[T](cls, values: list[T]) -> list[T]:
        return list(dict.fromkeys(values))

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _blank_currency(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("salary_currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def _currency_required_with_salary(self) -> PreferencesReplace:
        # An unlabelled number is useless to the salary dimension of the
        # ranking formula — 50000 could be anything.
        if self.min_salary_expectation is not None and self.salary_currency is None:
            raise ValueError("salary_currency is required when a minimum salary is set.")
        return self


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_roles: list[str]
    preferred_locations: list[str]
    preferred_work_modes: list[WorkMode]
    preferred_employment_types: list[EmploymentType]
    min_salary_expectation: Decimal | None
    salary_currency: str | None
    open_to_relocation: bool
    preferences_updated_at: datetime | None


class ProfileRead(BaseModel):
    """The full profile.

    Deliberately absent: education, work experience, projects and
    certifications. docs/api.md section 2.2 describes GET /profile as returning
    those too, but the tables and endpoints for them do not exist yet — they
    arrive with Phase 7. Naming that here so the schema is not read as a
    complete picture of the career profile.

    Also absent: `email`, which lives on User. A second copy would be a second
    source of truth.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID

    full_name: str | None
    headline: str | None
    location: str | None
    country_code: str | None
    phone: str | None
    summary: str | None
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None

    # Derived from the resume during parsing, user-overridable. Not editable
    # through this API yet — no writer populates them (see contact.py, which
    # deliberately declines to guess these).
    years_of_experience: Decimal | None
    current_experience_level: ExperienceLevel | None
    highest_education: EducationLevel | None

    target_roles: list[str]
    preferred_locations: list[str]
    preferred_work_modes: list[WorkMode]
    preferred_employment_types: list[EmploymentType]
    min_salary_expectation: Decimal | None
    salary_currency: str | None
    open_to_relocation: bool
    preferences_updated_at: datetime | None

    created_at: datetime
    updated_at: datetime
