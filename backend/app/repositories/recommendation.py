"""Relevance feedback storage (api.md section 2.5)."""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.models.enums import RecommendationFeedback
from app.models.recommendation import RecommendationFeedbackRow
from app.repositories.base import BaseRepository


class RecommendationFeedbackRepository(BaseRepository[RecommendationFeedbackRow]):
    model = RecommendationFeedbackRow

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        rating: RecommendationFeedback,
        ranking_version: str | None,
    ) -> None:
        """Save this user's opinion of one recommendation, replacing any prior one.

        An upsert rather than a read-then-decide: two taps in quick succession —
        entirely ordinary on a phone — would otherwise race between the SELECT
        and the INSERT and hit the unique index as an error the user did nothing
        to deserve. `ON CONFLICT DO UPDATE` makes changing your mind the same
        statement as stating it.

        `updated_at` is set explicitly because the column's `onupdate` is an ORM
        hook and this statement bypasses the ORM's unit of work.
        """
        statement = insert(RecommendationFeedbackRow).values(
            user_id=user_id,
            job_id=job_id,
            rating=rating,
            ranking_version=ranking_version,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "job_id"],
                set_={
                    "rating": statement.excluded.rating,
                    "ranking_version": statement.excluded.ranking_version,
                    "updated_at": func.now(),
                },
            )
        )
