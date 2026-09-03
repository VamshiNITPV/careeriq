"""Work history, education, project and certification data access.

One generic repository over four tables, because they genuinely share a shape:
the same provenance columns, the same unique key, and the same rule about not
overwriting a user's edit. Four near-identical classes would be four places to
fix the next time that rule changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.ids import uuid7
from app.models.career import Certification, EducationRecord, Project, WorkExperience
from app.models.resume import ResumeVersion
from app.repositories.base import BaseRepository


class CareerEntityRepository[ModelT: (WorkExperience, EducationRecord, Project, Certification)](
    BaseRepository[ModelT]  # type: ignore[type-var]
):
    async def list_for_user(self, user_id: uuid.UUID) -> list[ModelT]:
        stmt = select(self.model).where(self.model.user_id == user_id)
        # Newest first where there is a date to sort on. Undated rows sort last
        # rather than first, so a row the parser could not date does not head
        # someone's work history.
        order = getattr(self.model, "start_date", None) or getattr(
            self.model, "issued_date", None
        )
        if order is not None:
            stmt = stmt.order_by(order.desc().nullslast(), self.model.created_at.desc())
        return list((await self.session.scalars(stmt)).all())

    async def upsert_from_extraction(
        self, *, user_id: uuid.UUID, source_version_id: uuid.UUID, rows: Sequence[dict[str, Any]]
    ) -> int:
        """Write extracted entities, leaving user edits alone.

        `WHERE NOT is_user_verified` is in the SQL rather than in a read-then-
        decide, for the reason `CandidateSkillRepository` gives: a concurrent
        edit could otherwise slip between the read and the write, and a
        re-parse would silently revert it (US-2.4 AC2).

        Returns the number of rows offered, not the number written — a row
        skipped because the user had edited it is a success, not a failure.
        """
        if not rows:
            return 0

        values = [
            {
                "id": uuid7(),
                "user_id": user_id,
                "source_version_id": source_version_id,
                **row,
            }
            for row in rows
        ]

        stmt = pg_insert(self.model).values(values)
        updatable = {
            key: stmt.excluded[key]
            for key in values[0]
            if key not in {"id", "user_id", "content_key"}
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.model.user_id, self.model.content_key],
            set_={**updatable, "updated_at": func.now()},
            # The whole point.
            where=self.model.is_user_verified.is_(False),
        )
        await self.session.execute(stmt)
        return len(values)

    async def delete_stale(
        self,
        *,
        user_id: uuid.UUID,
        source_version_id: uuid.UUID,
        keep_keys: Sequence[str],
    ) -> int:
        """Drop rows this version produced that it no longer produces.

        A re-parse with a better extractor should supersede the previous
        reading, including removing an entry it now recognises as noise. User-
        verified rows are exempt: the user asserted those, and a parser change
        is not grounds to delete someone's job history.
        """
        stmt = delete(self.model).where(
            self.model.user_id == user_id,
            self.model.source_version_id == source_version_id,
            self.model.is_user_verified.is_(False),
        )
        if keep_keys:
            stmt = stmt.where(self.model.content_key.notin_(keep_keys))
        return (await self.session.execute(stmt)).rowcount or 0

    async def delete_for_resume(self, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        """Remove everything traceable to a deleted resume.

        Provenance decides, not whether the user confirmed it — the same rule
        as skills. An entry the user corrected while reviewing this document is
        still derived from it, and leaving it behind is what made a deleted
        resume appear to resurrect its contents.
        """
        versions = select(ResumeVersion.id).where(ResumeVersion.resume_id == resume_id)
        result = await self.session.execute(
            delete(self.model).where(
                self.model.user_id == user_id,
                self.model.source_version_id.in_(versions),
            )
        )
        return result.rowcount or 0

    async def count_for_resume(self, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        versions = select(ResumeVersion.id).where(ResumeVersion.resume_id == resume_id)
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(self.model)
                .where(
                    self.model.user_id == user_id,
                    self.model.source_version_id.in_(versions),
                )
            )
        ) or 0


class WorkExperienceRepository(CareerEntityRepository[WorkExperience]):
    model = WorkExperience


class EducationRepository(CareerEntityRepository[EducationRecord]):
    model = EducationRecord


class ProjectRepository(CareerEntityRepository[Project]):
    model = Project


class CertificationRepository(CareerEntityRepository[Certification]):
    model = Certification
