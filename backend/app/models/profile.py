"""Career profile model (database.md section 3.1).

One-to-one with `User`. Holds identity details and the career preferences that
feed the ranking formula's location and salary dimensions (ml.md section 4.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EducationLevel, EmploymentType, ExperienceLevel, WorkMode

if TYPE_CHECKING:
    from app.models.user import User


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
        create_type=False,
    )


class Profile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "profiles"

    # UNIQUE is what makes this one-to-one rather than one-to-many. Enforcing it
    # in the database rather than trusting the relationship configuration means
    # a bug in a worker cannot create a second profile.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # ---------------------------------------------------------------- identity
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    linkedin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---------------------------------------------------------------- career state
    # Derived from the resume during parsing, but user-overridable: an extraction
    # error must not permanently distort every match score (US-2.4).
    years_of_experience: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 1), nullable=True
    )
    current_experience_level: Mapped[ExperienceLevel | None] = mapped_column(
        _pg_enum(ExperienceLevel, "experience_level"), nullable=True
    )
    highest_education: Mapped[EducationLevel | None] = mapped_column(
        _pg_enum(EducationLevel, "education_level"), nullable=True
    )

    # ---------------------------------------------------------------- preferences
    # Arrays rather than join tables: these are free-text user preferences with
    # no shared identity or attributes of their own. Skills are the opposite
    # case and get a real taxonomy table (database.md section 3.1).
    target_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    preferred_work_modes: Mapped[list[WorkMode]] = mapped_column(
        ARRAY(_pg_enum(WorkMode, "work_mode")),
        nullable=False,
        server_default=text("'{}'::work_mode[]"),
    )
    preferred_employment_types: Mapped[list[EmploymentType]] = mapped_column(
        ARRAY(_pg_enum(EmploymentType, "employment_type")),
        nullable=False,
        server_default=text("'{}'::employment_type[]"),
    )

    min_salary_expectation: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    open_to_relocation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Bumped whenever preferences change. The recommendation cache key is derived
    # from this, so a preference edit invalidates cached rankings without needing
    # to enumerate and delete keys (US-1.4 AC2, ADR-008).
    preferences_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="profile", lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience >= 0",
            name="years_non_negative",
        ),
        CheckConstraint(
            "min_salary_expectation IS NULL OR min_salary_expectation >= 0",
            name="salary_non_negative",
        ),
        # ISO 4217 is always three characters. Catching this here stops malformed
        # currency codes reaching the salary dimension of the ranking formula.
        CheckConstraint(
            "salary_currency IS NULL OR char_length(salary_currency) = 3",
            name="currency_is_iso4217",
        ),
        CheckConstraint(
            "country_code IS NULL OR char_length(country_code) = 2",
            name="country_is_iso3166",
        ),
    )
