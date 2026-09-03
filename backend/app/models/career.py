"""Work history, education, projects and certifications (database.md 3.2).

Promoted out of JSONB because ranking and gap analysis query them directly: the
experience and education dimensions of the formula (ml.md section 4.1) compare
these rows against a job's requirements, and "which projects demonstrate
Kubernetes" has to be a query rather than a scan over blobs.

All four share `CareerEntityMixin` — the same provenance columns as
`candidate_skills`, for the same reason. A user asking why something is on their
profile deserves a better answer than "the parser decided", and a re-parse must
never revert an edit they made by hand (US-2.4 AC2).

Dates are stored at **month precision**, with the day set to 1. Resumes write
"Jan 2020 - Present" and "2019-2023"; inventing a day would be precision the
source never had.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EducationLevel, EmploymentType, WorkMode


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class CareerEntityMixin:
    """Ownership, provenance and the user-edit guard.

    `declared_attr` rather than plain columns: a mixin's ForeignKey object
    cannot be shared across four mappers — SQLAlchemy would bind the same
    instance to each table and raise. The callable makes one per class.
    """

    @declared_attr
    @classmethod
    def user_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )

    @declared_attr
    @classmethod
    def source_version_id(cls) -> Mapped[uuid.UUID | None]:
        # SET NULL, not CASCADE. Which resume produced a row decides whether it
        # is removed with that resume, and the deletion rule lives in the
        # service — but a row the user typed in by hand carries no source and
        # must survive any upload being deleted.
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("resume_versions.id", ondelete="SET NULL"),
            nullable=True,
        )

    @declared_attr
    @classmethod
    def content_key(cls) -> Mapped[str]:
        """Normalised fingerprint of the entity, for idempotent re-parsing.

        Without it a second parse of the same resume inserts a second copy of
        every job the candidate has ever held. Unique per user, so the upsert
        can say "update unless the user has edited this" in one statement —
        the same shape as `candidate_skills`, and for the same reason: a
        read-then-decide would let a concurrent edit slip between the two.
        """
        return mapped_column(String(200), nullable=False)

    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    is_user_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


def _entity_args(table: str) -> tuple[object, ...]:
    return (
        Index(f"ux_{table}_content", "user_id", "content_key", unique=True),
        Index(f"ix_{table}_user", "user_id"),
        Index(f"ix_{table}_source", "source_version_id"),
        CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_is_fraction",
        ),
    )


def _dated_args() -> tuple[object, ...]:
    return (
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name="dates_ordered",
        ),
        # A role cannot both be current and have ended. Enforced here because
        # the ranking formula reads is_current to compute "years of recent
        # experience", and a row claiming both makes that arithmetic nonsense.
        CheckConstraint("NOT (is_current AND end_date IS NOT NULL)", name="current_has_no_end"),
    )


class WorkExperience(Base, UUIDPrimaryKeyMixin, CareerEntityMixin, TimestampMixin):
    __tablename__ = "work_experiences"

    # Nullable, unlike `title`. "Freelance Web Developer, 2019-2021" and
    # "Independent Consultant" are real entries with no employer to name, and
    # discarding the whole row to satisfy a NOT NULL would lose the role, the
    # dates and the highlights to protect a field nothing scores on. A role
    # with no title, by contrast, is not a usable experience entry.
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    employment_type: Mapped[EmploymentType | None] = mapped_column(
        _pg_enum(EmploymentType, "employment_type"), nullable=True
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    work_mode: Mapped[WorkMode | None] = mapped_column(
        _pg_enum(WorkMode, "work_mode"), nullable=True
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The bullets under the role. Kept as written: they are the candidate's own
    # words, and are quoted back when a resume suggestion cites evidence.
    highlights: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )

    __table_args__ = (*_entity_args("work_experiences"), *_dated_args())


class EducationRecord(Base, UUIDPrimaryKeyMixin, CareerEntityMixin, TimestampMixin):
    __tablename__ = "education_records"

    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The comparable form. `degree` keeps what the resume said ("B.Tech");
    # this is what the education dimension of the ranking formula orders on.
    education_level: Mapped[EducationLevel | None] = mapped_column(
        _pg_enum(EducationLevel, "education_level"), nullable=True
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Free text on purpose: "8.4 CGPA", "First Class", "3.9/4.0" and "72%" are
    # all real, and forcing them into one number would either lose meaning or
    # invent a conversion.
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (*_entity_args("education_records"), *_dated_args())


class Project(Base, UUIDPrimaryKeyMixin, CareerEntityMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    highlights: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (*_entity_args("projects"), *_dated_args())


class Certification(Base, UUIDPrimaryKeyMixin, CareerEntityMixin, TimestampMixin):
    __tablename__ = "certifications"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    credential_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        *_entity_args("certifications"),
        CheckConstraint(
            "issued_date IS NULL OR expires_date IS NULL OR expires_date >= issued_date",
            name="dates_ordered",
        ),
    )
