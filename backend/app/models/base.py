"""Declarative base and shared column mixins.

Two things here are load-bearing beyond the obvious.

**The naming convention.** Without it, PostgreSQL invents constraint names and
Alembic autogenerates migrations that try to drop constraints by names that
differ between databases. Downgrades then fail on exactly the database you most
need them to work on. Setting it once, before any table exists, makes every
constraint name deterministic and derivable.

**Timestamps default server-side.** `func.now()` is evaluated by PostgreSQL, not
Python, so rows written by a migration, a raw SQL statement, or a worker on a
machine with a skewed clock all get consistent values from one source.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key (architecture.md section 4).

    The default is generated in Python rather than by `gen_random_uuid()` so the
    id is available before flush — needed when building related objects in one
    unit of work — and because PostgreSQL has no built-in v7 generator.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )


class TimestampMixin:
    """`created_at` and `updated_at`, both TIMESTAMPTZ in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        # onupdate is applied by SQLAlchemy on ORM updates. A database trigger
        # would also cover raw SQL; that is deferred until something actually
        # writes outside the ORM.
        onupdate=func.now(),
    )


class CreatedAtMixin:
    """`created_at` only — for append-only tables that are never modified.

    Giving an immutable row an `updated_at` invites code that updates it
    (database.md section 3.7, application_events).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SoftDeleteMixin:
    """Nullable `deleted_at`.

    Applied only where recovery genuinely matters — resumes and applications.
    Blanket soft deletion means every query needs a filter that will eventually
    be forgotten, silently resurrecting deleted rows (architecture.md section 4).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
