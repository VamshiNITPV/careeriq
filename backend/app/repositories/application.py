"""Saved-job and applied-flag data access."""

from __future__ import annotations

import uuid
from decimal import Decimal

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
        saved: bool,
        applied: bool,
        resume_version_id: uuid.UUID | None = None,
        match_score: Decimal | None = None,
    ) -> Application:
        """Set this user's relationship to this job, creating it if absent.

        **Two independent facts.** `saved` is the bookmark, `applied` is the
        funnel stage, and writing one never disturbs the other — which is the
        whole point of the split. Both are required rather than optional, so a
        caller states the complete desired state and a partial write cannot leave
        the row half-updated.

        Callers must not pass `saved=False, applied=False`: that row would mean
        nothing and the `saved_or_applied` CHECK rejects it. `DELETE` is how a
        relationship ends.

        One statement, not a read-then-decide. The toggle is a button someone
        taps twice on a phone, and a read followed by a write has a window a
        second tap fits through — the same reasoning the career repository
        records for its own upsert.

        `status` and `applied_at` are both derived here rather than passed in, so
        the invariant the `applied_has_timestamp` CHECK enforces cannot be
        violated by a caller, and the timestamp is `func.now()` so the value
        comes from PostgreSQL like every other one in the schema.

        **The snapshot moves with `applied_at`** (US-7.2 AC2). `resume_version_id`
        and `match_score` record what was true when the application was sent, and
        they are cleared alongside the timestamp when it is unsent — the three
        describe one event and must not disagree.

        Writing them once and never overwriting was the alternative, and it
        produces an incoherent row: `applied_at` already resets to `now()` on
        every re-apply, so a preserved snapshot would sit beside today's date
        describing the resume of three months ago.
        """
        status = ApplicationStatus.APPLIED if applied else ApplicationStatus.SAVED
        applied_at = func.now() if applied else None
        # Nothing is recorded for a bookmark. A saved job is not an application,
        # and a snapshot on one would put a match score in the funnel's
        # score-band table for a job nothing was ever sent to.
        version_id = resume_version_id if applied else None
        score = match_score if applied else None

        stmt = pg_insert(Application).values(
            id=uuid7(),
            user_id=user_id,
            job_id=job_id,
            status=status,
            is_saved=saved,
            applied_at=applied_at,
            resume_version_id=version_id,
            match_score_at_apply=score,
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
                "is_saved": stmt.excluded.is_saved,
                "applied_at": stmt.excluded.applied_at,
                "resume_version_id": stmt.excluded.resume_version_id,
                "match_score_at_apply": stmt.excluded.match_score_at_apply,
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

    async def get_for_user(
        self, *, user_id: uuid.UUID, application_id: uuid.UUID
    ) -> Application | None:
        """One live application the caller owns, by its own id.

        Scoped by `user_id` in the WHERE clause rather than fetched and then
        checked, so a caller asking for somebody else's application gets the
        same answer as one asking for an id that does not exist. The route turns
        that into a 404 — a 403 would confirm the row is real, which is a
        membership oracle over other people's job hunts.
        """
        return await self.session.scalar(
            select(Application).where(
                Application.id == application_id,
                Application.user_id == user_id,
                Application.deleted_at.is_(None),
            )
        )

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
