"""Skill taxonomy and candidate skill data access."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.data.skill_taxonomy import normalize_skill_text
from app.models.skill import CandidateSkill, Skill
from app.repositories.base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    model = Skill

    async def get_by_normalized_name(self, normalized: str) -> Skill | None:
        return await self.session.scalar(select(Skill).where(Skill.normalized_name == normalized))

    async def get_by_names(self, names: list[str]) -> dict[str, Skill]:
        """Bulk-resolve canonical names to rows.

        One query rather than one per skill: a resume yields dozens of matches,
        and a lookup per match turns parsing into a burst of round trips.
        """
        if not names:
            return {}
        stmt = select(Skill).where(Skill.name.in_(names))
        return {skill.name: skill for skill in (await self.session.scalars(stmt)).all()}

    async def search(self, query: str, *, limit: int = 20) -> list[Skill]:
        """Autocomplete over names and aliases.

        Aliases are searched too, so typing "postgres" finds PostgreSQL — which
        is the entire reason aliases exist.
        """
        normalized = normalize_skill_text(query)
        if not normalized:
            return []

        stmt = (
            select(Skill)
            .where(
                or_(
                    Skill.normalized_name.like(f"{normalized}%"),
                    Skill.normalized_name.like(f"%{normalized}%"),
                    Skill.aliases.any(normalized),  # type: ignore[attr-defined]
                )
            )
            # Prefix matches first: someone typing "java" wants Java before
            # JavaScript, and both before "Core Java Concepts".
            .order_by(
                Skill.normalized_name.like(f"{normalized}%").desc(),
                func.length(Skill.normalized_name),
                Skill.name,
            )
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def load_taxonomy(self) -> dict[str, list[str]]:
        """Canonical name -> every lookup form, for the matcher.

        Loaded once per pipeline run rather than queried per candidate term.
        """
        stmt = select(Skill.name, Skill.normalized_name, Skill.aliases)
        rows = (await self.session.execute(stmt)).all()
        return {name: [normalized, *(aliases or [])] for name, normalized, aliases in rows}

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Insert seed skills, refreshing `aliases` and `category` on existing ones.

        This was ON CONFLICT DO NOTHING, which was idempotent but silently
        useless for improvements: adding "oops" as an alias of Object-Oriented
        Programming, or "ms excel" to Excel, changed nothing because those
        skills already existed. The taxonomy could gain new rows but never get
        better at matching the ones it had — and the failure was invisible,
        because seeding still reported success.

        Only aliases and category are refreshed. `demand_score` is computed from
        the job corpus and `is_verified` may have been curated by an admin, so
        neither belongs to the seed file.
        """
        if not rows:
            return 0
        statement = pg_insert(Skill).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["normalized_name"],
            set_={
                "aliases": statement.excluded.aliases,
                "category": statement.excluded.category,
            },
        )
        result = await self.session.execute(statement)
        return result.rowcount or 0

    async def count(self) -> int:
        return (await self.session.scalar(select(func.count()).select_from(Skill))) or 0


class CandidateSkillRepository(BaseRepository[CandidateSkill]):
    model = CandidateSkill

    async def list_for_user(self, user_id: uuid.UUID) -> list[CandidateSkill]:
        stmt = (
            select(CandidateSkill)
            .where(CandidateSkill.user_id == user_id)
            .order_by(CandidateSkill.is_user_verified.desc(), CandidateSkill.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_owned(
        self, candidate_skill_id: uuid.UUID, user_id: uuid.UUID
    ) -> CandidateSkill | None:
        return await self.session.scalar(
            select(CandidateSkill).where(
                CandidateSkill.id == candidate_skill_id,
                CandidateSkill.user_id == user_id,
            )
        )

    async def get_for_skill(self, user_id: uuid.UUID, skill_id: uuid.UUID) -> CandidateSkill | None:
        return await self.session.scalar(
            select(CandidateSkill).where(
                CandidateSkill.user_id == user_id, CandidateSkill.skill_id == skill_id
            )
        )

    async def upsert_from_extraction(
        self,
        *,
        user_id: uuid.UUID,
        skill_id: uuid.UUID,
        confidence: Decimal,
        source_version_id: uuid.UUID,
    ) -> bool:
        """Write an extracted skill, never overwriting a user's own correction.

        This is the idempotency rule that makes re-parsing safe (US-2.4 AC2).
        The `WHERE NOT is_user_verified` clause is the whole point: without it,
        re-processing a resume would silently undo every manual fix the user
        made. Enforced in SQL rather than by reading first and deciding, so a
        concurrent edit cannot slip between the read and the write.

        Returns True if a row was inserted or updated.
        """
        statement = (
            pg_insert(CandidateSkill)
            .values(
                user_id=user_id,
                skill_id=skill_id,
                extraction_confidence=confidence,
                source_version_id=source_version_id,
                is_user_verified=False,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "skill_id"],
                set_={
                    "extraction_confidence": confidence,
                    "source_version_id": source_version_id,
                },
                where=CandidateSkill.is_user_verified.is_(False),
            )
        )
        result = await self.session.execute(statement)
        return bool(result.rowcount)

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(CandidateSkill)
                .where(CandidateSkill.user_id == user_id)
            )
        ) or 0
