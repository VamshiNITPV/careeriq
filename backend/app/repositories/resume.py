"""Resume and resume version data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update

from app.models.resume import Resume, ResumeVersion
from app.repositories.base import BaseRepository


class ResumeRepository(BaseRepository[Resume]):
    model = Resume

    async def get_owned(self, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume | None:
        """Fetch a resume only if this user owns it.

        Ownership is part of the query rather than a check after loading. A
        separate `if resume.user_id != user_id` is one forgotten line away from
        an access-control bug, and this shape makes it impossible to forget
        (US-1.5).
        """
        return await self.session.scalar(
            select(Resume).where(
                Resume.id == resume_id,
                Resume.user_id == user_id,
                Resume.deleted_at.is_(None),
            )
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[Resume]:
        stmt = (
            select(Resume)
            .where(Resume.user_id == user_id, Resume.deleted_at.is_(None))
            .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Resume)
                .where(Resume.user_id == user_id, Resume.deleted_at.is_(None))
            )
        ) or 0

    async def clear_primary(self, user_id: uuid.UUID) -> None:
        """Unset the current primary.

        Must run before setting a new one: a partial unique index enforces at
        most one primary per user, so setting the second first would violate it.
        """
        await self.session.execute(
            update(Resume)
            .where(Resume.user_id == user_id, Resume.is_primary.is_(True))
            .values(is_primary=False)
        )

    async def get_primary(self, user_id: uuid.UUID) -> Resume | None:
        return await self.session.scalar(
            select(Resume).where(
                Resume.user_id == user_id,
                Resume.is_primary.is_(True),
                Resume.deleted_at.is_(None),
            )
        )

    async def set_current_version(self, resume_id: uuid.UUID, version_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Resume).where(Resume.id == resume_id).values(current_version_id=version_id)
        )


class ResumeVersionRepository(BaseRepository[ResumeVersion]):
    model = ResumeVersion

    async def next_version_number(self, resume_id: uuid.UUID) -> int:
        """Next sequence number for a resume.

        A unique index on (resume_id, version_number) is the real guarantee;
        this computes the usual case. Two simultaneous uploads to one resume
        would race here and the loser gets an integrity error rather than a
        duplicated version — the correct failure.
        """
        highest = await self.session.scalar(
            select(func.max(ResumeVersion.version_number)).where(
                ResumeVersion.resume_id == resume_id
            )
        )
        return (highest or 0) + 1

    async def get_owned(self, version_id: uuid.UUID, user_id: uuid.UUID) -> ResumeVersion | None:
        return await self.session.scalar(
            select(ResumeVersion)
            .join(Resume, Resume.id == ResumeVersion.resume_id)
            .where(
                ResumeVersion.id == version_id,
                Resume.user_id == user_id,
                Resume.deleted_at.is_(None),
            )
        )

    async def list_for_resume(self, resume_id: uuid.UUID) -> list[ResumeVersion]:
        stmt = (
            select(ResumeVersion)
            .where(ResumeVersion.resume_id == resume_id)
            .order_by(ResumeVersion.version_number.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def find_by_content_hash(
        self, user_id: uuid.UUID, content_hash: str
    ) -> ResumeVersion | None:
        """Find an identical file this user already uploaded.

        Lets a re-upload skip the whole pipeline instead of spending CPU to
        produce a result we already have.
        """
        return await self.session.scalar(
            select(ResumeVersion)
            .join(Resume, Resume.id == ResumeVersion.resume_id)
            .where(
                Resume.user_id == user_id,
                ResumeVersion.content_hash == content_hash,
                Resume.deleted_at.is_(None),
            )
            .order_by(ResumeVersion.created_at.desc())
        )
