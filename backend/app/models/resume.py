"""Resume and resume version models (database.md section 3.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    CreatedAtMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.enums import ProcessingStatus


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class Resume(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """The logical resume. The file itself belongs to a version."""

    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Nullable, because a resume exists before its first version finishes
    # parsing — making this NOT NULL would make the pair impossible to insert
    # without a deferred constraint. It is still a real foreign key, so the
    # column cannot point at a version that does not exist.
    #
    # use_alter is required: resumes and resume_versions reference each other,
    # and without it SQLAlchemy cannot order CREATE TABLE for the cycle. The
    # explicit name keeps the constraint identical to the one the migration
    # creates, which is what `alembic check` compares.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "resume_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_resumes_current_version_id_resume_versions",
        ),
        nullable=True,
    )

    # foreign_keys is required: two foreign keys link these tables —
    # resume_versions.resume_id (a version belongs to a resume) and
    # resumes.current_version_id (a resume points at one version). Without this,
    # SQLAlchemy cannot tell which path the relationship follows and refuses to
    # configure the mapper at all.
    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="desc(ResumeVersion.version_number)",
        lazy="selectin",
        foreign_keys="ResumeVersion.resume_id",
    )

    __table_args__ = (
        # Partial unique index: exactly one primary resume per user, enforced by
        # the database rather than by application code that can be bypassed.
        Index(
            "ux_resumes_one_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary AND deleted_at IS NULL"),
        ),
        Index("ix_resumes_user_id", "user_id"),
    )


class ResumeVersion(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """An immutable snapshot of one uploaded file and everything parsed from it.

    No `updated_at`: versions are never edited. Corrections are applied to the
    extracted profile rows, not to the version, so the record of what the parser
    actually produced stays intact and auditable (US-2.5).
    """

    __tablename__ = "resume_versions"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Generated UUID key, never the client filename (ADR-014).
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # SHA-256 of the file. Lets a re-upload of an identical document skip the
    # whole pipeline instead of burning CPU to produce the same result.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Detected sections with their character spans, and raw extractor output
    # with confidences. JSONB because the shape changes as the parser improves;
    # anything the application depends on is promoted to real columns and tables
    # (database.md section 3.2).
    parsed_sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    parsed_entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        _pg_enum(ProcessingStatus, "processing_status"),
        nullable=False,
        default=ProcessingStatus.PENDING,
        server_default=ProcessingStatus.PENDING.value,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resume: Mapped[Resume] = relationship(
        back_populates="versions", lazy="joined", foreign_keys=[resume_id]
    )

    __table_args__ = (
        Index("ux_resume_versions_number", "resume_id", "version_number", unique=True),
        Index("ix_resume_versions_hash", "content_hash"),
        CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 5242880",
            name="file_size_within_limit",
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
    )

    @property
    def is_complete(self) -> bool:
        return self.processing_status is ProcessingStatus.COMPLETE
