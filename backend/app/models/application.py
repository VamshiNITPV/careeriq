"""What a user has done about a job: saved it, and whether they applied.

The first slice of database.md section 3.7. That table was specified with twelve
columns and seven statuses for a funnel with analytics; this builds the part the
interface can actually drive today, and each omitted column has a precondition
that does not exist yet — see the module's `__table_args__` and section 3.7's
as-built note.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ApplicationStatus
from app.models.job import Job


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Reference a native enum the migration owns.

    `create_type=False` is load-bearing: without it SQLAlchemy emits CREATE TYPE
    on every table create and the migration fails on the second run.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class Application(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One user's relationship to one job.

    **Two independent facts, not one.** `is_saved` is the user's bookmark;
    `status` is how far the job has got. A job can be bookmarked, applied to, or
    both, and neither action implies the other — conflating them meant ticking
    "I have applied" silently bookmarked the job as well.

    Soft-deleted, which is what `SoftDeleteMixin` was written for — its docstring
    names resumes and applications as the only two places recovery genuinely
    matters. Here it does real work on the one path that still removes a row:
    dropping a job that is neither bookmarked nor applied leaves a tombstone
    carrying the fact that the user once applied, so that history survives an
    action they may regret.
    """

    __tablename__ = "applications"

    # CASCADE, unlike jobs.submitted_by_user_id which is SET NULL. A posting
    # someone pasted is a fact about the market and outlives their account; what
    # they saved is their own data and goes with them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: an application is historical fact (database.md section 3.7). If
    # deleting a job cascaded these away, the funnel would lose data with no
    # error. Nothing deletes a job today, so this costs nothing yet — but see the
    # as-built note about ADR-019's per-provider removal path, which now needs
    # two statements rather than one.
    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        _pg_enum(ApplicationStatus, "application_status"),
        nullable=False,
        default=ApplicationStatus.SAVED,
        server_default=text("'SAVED'::application_status"),
    )
    # Whether the user bookmarked this job, independently of where it sits in
    # the funnel.
    #
    # Separate from `status` because the two are different facts and conflating
    # them was a reported bug: `status` held SAVED *or* APPLIED, so marking a job
    # applied was indistinguishable from bookmarking it, and the interface filled
    # the bookmark on the user's behalf for something they had not done. A funnel
    # stage answers "how far has this got"; this answers "did I bookmark it".
    is_saved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Set when the user marks it applied, cleared when they unmark it. The
    # profile list shows it.
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Joined, not lazy. Every path that serialises an application needs the job,
    # and a lazy load in async has no await point — that is MissingGreenlet at
    # render time rather than at the attribute access.
    job: Mapped[Job] = relationship(lazy="joined")

    __table_args__ = (
        # The whole idempotency mechanism for the save toggle: at most one live
        # application per (user, job), enforced by the database rather than by a
        # read-then-write that a double-tap can slip between.
        #
        # Partial on `deleted_at IS NULL`, which is also what makes unsave then
        # re-save insert a fresh row rather than collide with the tombstone —
        # deliberate, so a job you unsaved after applying comes back SAVED
        # instead of silently re-asserting that you applied.
        Index(
            "ux_applications_user_job",
            "user_id",
            "job_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Not automatic on a foreign key. RESTRICT makes every DELETE on jobs
        # check this table, and without an index that is a sequential scan per
        # row deleted. Same reason jobs declares ix_jobs_company.
        Index("ix_applications_job_id", "job_id"),
        # A row whose status contradicts its timestamp is a row nothing can
        # trust. Modelled on jobs' duplicate_has_canonical, and it holds in both
        # directions so unmarking applied must clear the date.
        CheckConstraint(
            "(status = 'APPLIED') = (applied_at IS NOT NULL)",
            name="applied_has_timestamp",
        ),
        # A live row has to mean something. Once `is_saved` and `status` became
        # independent, "not bookmarked and not applied" stopped being a state
        # with any content — there is nothing left to remember about the job, so
        # the row is deleted rather than kept as an empty relationship. The API
        # rejects that combination too; this is the backstop that makes it
        # unreachable by any other writer.
        CheckConstraint(
            "is_saved OR status = 'APPLIED'",
            name="saved_or_applied",
        ),
        # database.md section 3.7 also specifies ix_applications_status on
        # (user_id, status, last_status_change_at DESC). Not built: that column
        # does not exist here, and ux_applications_user_job already leads on
        # user_id with the same partial predicate, so it serves the profile
        # queries while the heap filters two status values over tens of rows.
        # When a funnel or real volume arrives it returns as
        # (user_id, status, created_at DESC).
    )
