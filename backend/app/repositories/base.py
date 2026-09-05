"""Repository base.

Repositories are the only layer holding a `Session` (architecture.md section 2).
They contain queries and persistence, never business rules — an
`if user.is_active` decision belongs in a service, because that is a policy, not
a storage concern.

Repositories deliberately do NOT commit. The session dependency owns the
transaction boundary for a request (core/database.py), so a service can make
several repository calls and have them succeed or fail together. A repository
that commits on its own makes that impossible.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.models.base import Base


class BaseRepository[ModelT: Base]:
    """PEP 695 type parameter syntax — the `Generic[T]` + `TypeVar` pair it
    replaces is legacy on Python 3.12+."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_many(self, entity_ids: list[uuid.UUID]) -> list[ModelT]:
        if not entity_ids:
            return []
        stmt = select(self.model).where(self.model.id.in_(entity_ids))  # type: ignore[attr-defined]
        return list((await self.session.scalars(stmt)).all())

    def add(self, entity: ModelT) -> ModelT:
        """Stage a new row. Not persisted until flush or commit."""
        self.session.add(entity)
        return entity

    async def flush(self) -> None:
        """Send pending SQL without ending the transaction.

        Needed when a subsequent statement depends on this write — for example
        to surface a unique-violation before continuing, or to get a
        database-generated default back.
        """
        await self.session.flush()

    def savepoint(self) -> AsyncSessionTransaction:
        """A SAVEPOINT around one unit of work inside a larger transaction.

        Needed wherever a loop must survive a failure that reaches the database.
        `except Exception: continue` is not sufficient on its own: once a flush
        raises, the session is in a failed state, every later statement dies of
        PendingRollbackError, and the request then fails at commit — so one bad
        record takes the whole batch down, not just itself.

        Used as `async with repo.savepoint():`. Leaving the block by exception
        rolls back to the savepoint and leaves the outer transaction usable, so
        the caller's `except` can record the failure and carry on.
        """
        return self.session.begin_nested()

    async def refresh(self, entity: ModelT) -> None:
        """Reload an instance after a flush that touched server-side defaults.

        A column with `onupdate=func.now()` — every `updated_at` in this
        codebase — is computed by PostgreSQL, so SQLAlchemy marks the attribute
        expired once the UPDATE is issued. Reading it afterwards triggers a
        lazy load, and in async that load needs an await point it does not
        have, producing `MissingGreenlet` at serialisation time rather than at
        the access.

        `expire_on_commit=False` does not cover this: the expiry happens on
        flush, not on commit. Any service that flushes and then returns the
        object for serialisation must refresh it first.
        """
        await self.session.refresh(entity)

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)

    async def commit(self) -> None:
        """End the transaction immediately.

        Almost never the right call — the request owns the transaction boundary
        (core/database.py), and committing mid-request breaks the guarantee that
        a failed request leaves no partial writes.

        The one legitimate use is a side effect that must survive the failure it
        accompanies: revoking a token family on reuse detection must persist
        even though the request then raises. Every call site must justify itself
        in a comment.
        """
        await self.session.commit()

    async def exists(self, **filters: Any) -> bool:
        """Existence check that does not transfer the row.

        `SELECT 1 ... LIMIT 1` rather than loading the entity and testing for
        None, which would pull every column across the wire to answer a boolean.
        """
        stmt = select(1).select_from(self.model).limit(1)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        return (await self.session.scalar(stmt)) is not None
