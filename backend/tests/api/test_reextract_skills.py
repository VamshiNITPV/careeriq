"""Re-extracting skills after a taxonomy change (2026-09-12).

The two sides deliberately behave differently, and both differences are worth
pinning: a posting's skills are fully replaced because they are a fact about the
posting, while a profile is only ever added to because it holds decisions the
user made.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.job.reextract_skills import reextract_job_skills
from app.services.resume.reextract_skills import reextract_candidate_skills
from tests.api.test_jobs import BACKEND_BODY, submit_job, upload_and_parse

API = "/api/v1"


class TestJobSkills:
    async def test_re_reading_a_posting_is_idempotent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Twice over the same text with the same taxonomy must land in the same
        place. Without this, a re-extraction that could be run safely once is a
        migration nobody dares repeat."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)

        first = await reextract_job_skills(db_session)
        second = await reextract_job_skills(db_session)

        assert first.skills_after == second.skills_after
        assert first.lost_skills == 0
        # Nothing changed the second time, because nothing could have.
        assert second.changed == 0

    async def test_it_reports_rather_than_hides_a_loss(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """`lost_skills` exists so an additive taxonomy change that somehow
        removes skills is visible instead of being averaged into a total."""
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)

        result = await reextract_job_skills(db_session)

        assert result.considered >= 1
        assert result.skills_after >= result.skills_before
        assert result.lost_skills == 0


class TestCandidateSkills:
    async def test_a_user_verified_skill_is_never_overwritten(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The whole reason this is safe to run against real profiles.

        A profile holds skills the user confirmed and skills they typed in
        themselves. Re-reading their resume must not quietly revise either, and
        the guarantee lives in SQL (`WHERE NOT is_user_verified`) rather than in
        a read-then-decide that a concurrent edit could slip between.
        """
        await upload_and_parse(client, auth_headers, run_pipeline)

        marked = await db_session.execute(
            text("""
                UPDATE candidate_skills
                SET is_user_verified = true, extraction_confidence = 0.111
                WHERE id = (SELECT id FROM candidate_skills LIMIT 1)
                RETURNING skill_id
            """)
        )
        skill_id = marked.scalar_one()
        await db_session.commit()

        await reextract_candidate_skills(db_session)
        await db_session.commit()

        row = (
            await db_session.execute(
                text("""
                    SELECT is_user_verified, extraction_confidence
                    FROM candidate_skills WHERE skill_id = :s
                """),
                {"s": skill_id},
            )
        ).one()
        assert row[0] is True
        # The sentinel confidence survived, so the row was genuinely not rewritten.
        assert float(row[1]) == 0.111

    async def test_it_only_ever_adds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """No deletion path, by construction.

        The job side calls `replace_for_job`, which drops rows first. This side
        must not, because a row absent from the new reading may be one the user
        added by hand.
        """
        await upload_and_parse(client, auth_headers, run_pipeline)
        before = await db_session.scalar(text("SELECT count(*) FROM candidate_skills"))

        await reextract_candidate_skills(db_session)
        await db_session.commit()

        after = await db_session.scalar(text("SELECT count(*) FROM candidate_skills"))
        assert after >= before

    async def test_a_hand_added_skill_survives(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """A skill the resume never mentions, typed in by the user, stays.

        This is the case the `replace` shape on the job side would destroy, and
        the reason the two sides are not the same function.
        """
        await upload_and_parse(client, auth_headers, run_pipeline)

        # A skill deliberately unrelated to the fixture resume's text.
        skill_id = await db_session.scalar(
            text("SELECT id FROM skills WHERE name = 'COBOL' OR name = 'LaTeX' LIMIT 1")
        )
        assert skill_id is not None, "expected a taxonomy entry absent from the fixture resume"
        user_id = await db_session.scalar(text("SELECT id FROM users LIMIT 1"))
        await db_session.execute(
            text("""
                INSERT INTO candidate_skills (id, user_id, skill_id, is_user_verified)
                VALUES (:i, :u, :s, true)
                ON CONFLICT (user_id, skill_id) DO UPDATE SET is_user_verified = true
            """),
            {"i": uuid.uuid4(), "u": user_id, "s": skill_id},
        )
        await db_session.commit()

        await reextract_candidate_skills(db_session)
        await db_session.commit()

        still_there = await db_session.scalar(
            text("SELECT count(*) FROM candidate_skills WHERE skill_id = :s"), {"s": skill_id}
        )
        assert still_there == 1


class TestRejectionSurvives:
    """The bug this column exists for.

    Removing a skill used to delete the row, which records that the skill is
    absent but not that anyone decided it should be — so the next parse found
    the term and put it straight back. Reported early in the project, then
    reproduced on 2026-09-12 when a taxonomy change triggered a re-extraction.
    """

    async def test_a_removed_skill_does_not_come_back(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        await upload_and_parse(client, auth_headers, run_pipeline)

        listed = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert listed, "the fixture resume should yield at least one skill"
        target = listed[0]

        removed = await client.delete(f"{API}/profile/skills/{target['id']}", headers=auth_headers)
        assert removed.status_code == 200, removed.text

        # Gone from the profile immediately.
        after_delete = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert target["id"] not in [row["id"] for row in after_delete]

        # And still gone after the resume is read again, which is the part that
        # used to fail.
        await reextract_candidate_skills(db_session)
        await db_session.commit()

        after_reextract = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        names = [row["skill"]["name"] for row in after_reextract]
        assert target["skill"]["name"] not in names

    async def test_adding_it_back_clears_the_rejection(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The only way the tombstone clears.

        Without this the user would be stuck: a skill they removed by accident
        could never be added back, and the control that would fix it is hidden
        by the very row that needs changing.
        """
        await upload_and_parse(client, auth_headers, run_pipeline)
        listed = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        target = listed[0]
        await client.delete(f"{API}/profile/skills/{target['id']}", headers=auth_headers)

        added = await client.post(
            f"{API}/profile/skills",
            headers=auth_headers,
            json={"skill_id": target["skill"]["id"]},
        )

        assert added.status_code in (200, 201), added.text
        back = (await client.get(f"{API}/profile/skills", headers=auth_headers)).json()
        assert target["skill"]["name"] in [row["skill"]["name"] for row in back]

    async def test_a_row_cannot_be_both_confirmed_and_refused(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """They are contradictory claims, and the CHECK makes that unreachable."""
        await upload_and_parse(client, auth_headers, run_pipeline)

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text("UPDATE candidate_skills SET is_user_verified = true, is_rejected = true")
            )
            await db_session.flush()
        await db_session.rollback()
