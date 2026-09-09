"""Saved-job and applied-flag data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.ids import uuid7
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository[Application]):
    model = Application

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        status: ApplicationStatus,
    ) -> Application:
        """Set this user's application to this job, creating it if absent.

        One statement, not a read-then-decide. The toggle is a button someone
        taps twice on a phone, and a read followed by a write has a window a
        second tap fits through — the same reasoning the career repository
        records for its own upsert.

        `applied_at` is derived here rather than passed in, so the invariant the
        `applied_has_timestamp` CHECK enforces cannot be violated by a caller,
        and it is `func.now()` so the value comes from PostgreSQL like every
        other timestamp in the schema.
        """
        applied_at = func.now() if status is ApplicationStatus.APPLIED else None

        stmt = pg_insert(Application).values(
            id=uuid7(),
            user_id=user_id,
            job_id=job_id,
            status=status,
            applied_at=applied_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Application.user_id, Application.job_id],
            # Required, and the easiest thing to leave out. The arbiter index is
            # PARTIAL, and PostgreSQL will not infer a partial index without a
            # predicate matching it exactly — omit this and every call raises
            # 42P10 "no unique or exclusion constraint matching the ON CONFLICT
            # specification" at runtime, with nothing failing until then.
            index_where=Application.deleted_at.is_(None),
            set_={
                "status": stmt.excluded.status,
                "applied_at": stmt.excluded.applied_at,
                # `onupdate=func.now()` is an ORM-level hook and does not fire
                # for a Core insert, so without this line updated_at stays at
                # the original save time forever.
                "updated_at": func.now(),
            },
        )
        await self.session.execute(stmt)

        # Re-read rather than RETURNING: one indexed lookup buys a fully loaded
        # instance with `job` joined, which is what the response needs, and
        # avoids the expired-attribute hazard that makes a flushed row raise
        # MissingGreenlet at serialisation.
        application = await self.get_for_job(user_id=user_id, job_id=job_id)
        if application is None:  # pragma: no cover - the row was just written here
            raise RuntimeError("The application vanished between its upsert and its read.")
        return application

    async def get_for_job(self, *, user_id: uuid.UUID, job_id: uuid.UUID) -> Application | None:
        """The live application, if there is one. Tombstones are not returned."""
        return await self.session.scalar(
            select(Application).where(
                Application.user_id == user_id,
                Application.job_id == job_id,
                Application.deleted_at.is_(None),
            )
        )

    async def for_jobs(
        self, *, user_id: uuid.UUID, job_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Application]:
        """This caller's live applications for several jobs, keyed by job id.

        One query rather than one per card. At most one row per (user, job) is
        possible — a partial unique index guarantees it — so the mapping cannot
        lose anything.
        """
        if not job_ids:
            return {}
        rows = await self.session.scalars(
            select(Application).where(
                Application.user_id == user_id,
                Application.job_id.in_(job_ids),
                Application.deleted_at.is_(None),
            )
        )
        return {row.job_id: row for row in rows.all()}

    async def soft_delete(self, *, user_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Remove the user's application to this job. Returns whether one went.

        Scoped by `user_id` in the WHERE clause rather than by fetching and
        checking ownership, so it is structurally incapable of touching someone
        else's row — there is no id for a caller to supply and therefore none to
        enumerate.

        Soft, so the fact that someone once applied survives them unsaving it.
        """
        result = await self.session.execute(
            update(Application)
            .where(
                Application.user_id == user_id,
                Application.job_id == job_id,
                Application.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return bool(result.rowcount)

    async def list_for_user(
        self, *, user_id: uuid.UUID, status: ApplicationStatus | None = None
    ) -> list[Application]:
        """Live applications, newest first.

        Deliberately does not filter on the job's status. An application records
        what the user did; hiding one because the corpus later reclassified that
        posting as a duplicate would make entries vanish from their list with no
        explanation.
        """
        stmt = select(Application).where(
            Application.user_id == user_id, Application.deleted_at.is_(None)
        )
        if status is not None:
            stmt = stmt.where(Application.status == status)
        # By when it entered the list, not by updated_at, so a row does not jump
        # to the top merely because it was toggled.
        stmt = stmt.order_by(Application.created_at.desc())
        return list((await self.session.scalars(stmt)).unique().all())
