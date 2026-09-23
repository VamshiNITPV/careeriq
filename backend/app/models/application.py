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
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, text
from sqlalchemy import Enum as SAEnum
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
from app.models.enums import ApplicationEventType, ApplicationStatus
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

    # ------------------------------------------------- the snapshot (US-7.2 AC2)
    #
    # What was true when this was sent, recorded because it cannot be recovered
    # later. Next month the resume has been edited and the corpus has moved, so
    # "which resume did I use and how good was the match" has no answer unless
    # it was written down at the time.
    #
    # Both nullable, and all three reasons are ordinary: the user may have
    # uploaded no resume, the vectors may not exist yet, and scoring is allowed
    # to fail without taking the application down with it.
    #
    # **SET NULL, never CASCADE.** database.md section 3.7 warns that cascading
    # from a resume would make the funnel "quietly lose data". Deleting an old
    # resume must not delete the record that you applied to twelve jobs with it
    # -- the applications outlive the file, and the analytics read them.
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The overall score at the moment of applying.
    #:
    #: The number, not a band. Bands are a presentation choice and this keeps
    #: changing them a query change rather than a migration.
    match_score_at_apply: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

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
        # `applied_at` records that the application was actually sent, so it is
        # required from APPLIED onward and forbidden at SAVED.
        #
        # Terminal statuses are exempt rather than required to carry one. AC1
        # makes REJECTED and WITHDRAWN reachable from any active state including
        # SAVED, and a job somebody bookmarked and then withdrew was never
        # applied to — inventing a date for it would put a fabricated
        # application into the funnel counts.
        CheckConstraint(
            "CASE"
            " WHEN status = 'SAVED' THEN applied_at IS NULL"
            " WHEN status IN ('REJECTED', 'WITHDRAWN') THEN true"
            " ELSE applied_at IS NOT NULL"
            " END",
            name="applied_has_timestamp",
        ),
        # A live row has to mean something. Once `is_saved` and `status` became
        # independent, "not bookmarked and not applied" stopped being a state
        # with any content — there is nothing left to remember about the job, so
        # the row is deleted rather than kept as an empty relationship. The API
        # rejects that combination too; this is the backstop that makes it
        # unreachable by any other writer.
        # Was `is_saved OR status = 'APPLIED'`, which refused an unbookmarked
        # application the moment it reached ASSESSMENT. The rule it meant is
        # unchanged: a row that is neither bookmarked nor past SAVED has nothing
        # left to remember, and is deleted rather than kept empty.
        CheckConstraint(
            "is_saved OR status <> 'SAVED'",
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


class ApplicationEvent(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One thing that happened to an application (US-7.1 AC2).

    **Append-only.** No `updated_at`, and nothing updates a row: a correction is
    another event, not an edit. That is the whole value of the log — a funnel
    built on numbers that can be quietly rewritten is a funnel nobody should
    trust, and the analytics in US-7.2 read from here.

    It also holds the one thing `applications.status` cannot: *where* an
    application stopped. A row reading REJECTED says nothing about whether that
    happened after a phone screen or the day it was sent, and those are
    different outcomes to anyone looking at their own results.
    """

    __tablename__ = "application_events"
    __table_args__ = (
        # An event that changes nothing is noise in a record whose worth is that
        # every row means something happened. NULL `from_status` is the
        # exception: that row records the application coming into existence.
        CheckConstraint("from_status IS NULL OR from_status <> to_status", name="ck_events_move"),
        Index(
            "ix_application_events_application_occurred",
            "application_id",
            "occurred_at",
        ),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: NULL only on the event that records the application being created.
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        _pg_enum(ApplicationStatus, "application_status"), nullable=True
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(
        _pg_enum(ApplicationStatus, "application_status"), nullable=False
    )
    event_type: Mapped[ApplicationEventType] = mapped_column(
        _pg_enum(ApplicationEventType, "application_event_type"),
        nullable=False,
        default=ApplicationEventType.STATUS_CHANGE,
        server_default=ApplicationEventType.STATUS_CHANGE.value,
    )

    #: When it happened, which is not always when it was recorded.
    #:
    #: Separate from `created_at` because a user tells us about an interview
    #: after it happened. Collapsing them would date every event to the moment
    #: someone got round to logging it, and the funnel's timings would measure
    #: their record-keeping rather than their job hunt.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Room for what a future event type needs. Named with a trailing underscore
    #: because `metadata` is taken by SQLAlchemy's declarative base.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata_", JSONB, nullable=True)
