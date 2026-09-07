"""Saving jobs and marking them applied (US-7.0)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from tests.api.test_jobs import API, posting, submission


async def make_job(
    client: AsyncClient, headers: dict[str, str], title: str = "Backend Engineer"
) -> str:
    response = await client.post(
        f"{API}/jobs", headers=headers, json=submission(posting(title=title))
    )
    assert response.status_code == 201, response.text
    return str(response.json()["job"]["id"])


async def live_rows(session: AsyncSession, job_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.job_id == uuid.UUID(job_id), Application.deleted_at.is_(None))
        )
        or 0
    )


class TestSavingAndApplying:
    async def test_saving_twice_is_one_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The double-tap test.

        A bookmark is a control people tap twice on a phone. The upsert keys on
        a partial unique index rather than reading first, so the second tap is
        the same write, not a conflict.
        """
        job_id = await make_job(client, auth_headers)

        first = await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})
        second = await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        assert first.status_code == 200, first.text
        # 200 both times, never 201 on the first: varying the status by which
        # one happened is what makes retrying unsafe.
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["status"] == "SAVED"
        assert await live_rows(db_session, job_id) == 1

    async def test_marking_applied_and_back_again(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Exercises the applied_has_timestamp CHECK in both directions."""
        job_id = await make_job(client, auth_headers)
        saved = await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        applied = await client.put(
            f"{API}/jobs/{job_id}/application", headers=auth_headers, json={"status": "APPLIED"}
        )
        assert applied.json()["status"] == "APPLIED"
        assert applied.json()["applied_at"] is not None
        # The same row, not a second one.
        assert applied.json()["id"] == saved.json()["id"]

        # Unmarking sends SAVED rather than DELETE: the job stays saved.
        back = await client.put(
            f"{API}/jobs/{job_id}/application", headers=auth_headers, json={"status": "SAVED"}
        )
        assert back.json()["status"] == "SAVED"
        assert back.json()["applied_at"] is None

    async def test_marking_applied_on_a_job_never_saved(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Applying implies saving. One row, created straight into APPLIED.
        job_id = await make_job(client, auth_headers)

        response = await client.put(
            f"{API}/jobs/{job_id}/application", headers=auth_headers, json={"status": "APPLIED"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "APPLIED"

    async def test_an_unknown_job_is_404_and_writes_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Pins the fetch-before-upsert ordering.

        Without it the RESTRICT foreign key rejects the insert and the
        IntegrityError reaches the client through the catch-all as an opaque
        500 rather than a 404 naming the problem.
        """
        missing = uuid.uuid4()

        response = await client.put(
            f"{API}/jobs/{missing}/application", headers=auth_headers, json={}
        )

        assert response.status_code == 404
        assert (
            await db_session.scalar(
                select(func.count()).select_from(Application).where(Application.job_id == missing)
            )
        ) == 0

    async def test_removing_is_idempotent_and_soft(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        job_id = await make_job(client, auth_headers)
        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        first = await client.delete(f"{API}/jobs/{job_id}/application", headers=auth_headers)
        second = await client.delete(f"{API}/jobs/{job_id}/application", headers=auth_headers)

        # 204 even with nothing to remove, or a double-tap on unsave becomes a
        # visible error.
        assert first.status_code == 204
        assert second.status_code == 204
        assert await live_rows(db_session, job_id) == 0
        # Soft: the row is still there, carrying what happened.
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(Application)
                .where(Application.job_id == uuid.UUID(job_id))
            )
        ) == 1

        listing = await client.get(f"{API}/applications", headers=auth_headers)
        assert listing.json()["items"] == []
        detail = await client.get(f"{API}/jobs/{job_id}", headers=auth_headers)
        assert detail.json()["application"] is None

    async def test_re_saving_after_removal_starts_fresh(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """A deliberate decision, not a quirk of the index.

        The partial unique index does not cover tombstones, so re-saving inserts
        rather than resurrecting. That is what should happen: a job you unsaved
        after applying comes back SAVED, not silently re-asserting that you
        applied to it, and the tombstone keeps the original fact.
        """
        job_id = await make_job(client, auth_headers)
        applied = await client.put(
            f"{API}/jobs/{job_id}/application", headers=auth_headers, json={"status": "APPLIED"}
        )
        await client.delete(f"{API}/jobs/{job_id}/application", headers=auth_headers)

        again = await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        assert again.json()["id"] != applied.json()["id"]
        assert again.json()["status"] == "SAVED"
        assert again.json()["applied_at"] is None

    async def test_a_second_live_row_is_impossible(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        registered_user: dict[str, object],
        seeded_skills: int,
    ) -> None:
        # The database, not the service, is what makes the toggle safe.
        job_id = await make_job(client, auth_headers)
        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})
        user_id = uuid.UUID(str(registered_user["user"]["id"]))  # type: ignore[index]

        # Inside a savepoint, so the expected failure is contained. A bare
        # session.rollback() here would unwind the transaction the fixture holds
        # the whole test in, taking the registered user with it and leaking into
        # later tests in the same run.
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(Application(user_id=user_id, job_id=uuid.UUID(job_id)))
                await db_session.flush()

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.put(f"{API}/jobs/{uuid.uuid4()}/application", json={})
        assert response.status_code == 401


class TestTheJobListReflectsIt:
    async def test_a_user_with_nothing_saved_still_sees_every_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The LEFT-JOIN regression test.

        Move any of the join's predicates from ON into WHERE and it degrades to
        an inner join: every job the caller has not saved disappears from browse
        with nothing failing anywhere. This is the test that catches it.
        """
        await make_job(client, auth_headers, title="Alpha Engineer")
        await make_job(client, auth_headers, title="Beta Engineer")

        listing = await client.get(f"{API}/jobs", headers=auth_headers)

        assert listing.json()["total"] == 2
        assert all(item["application"] is None for item in listing.json()["items"])

    async def test_a_saved_job_carries_its_application(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        alpha = await make_job(client, auth_headers, title="Alpha Engineer")
        await make_job(client, auth_headers, title="Beta Engineer")
        await client.put(
            f"{API}/jobs/{alpha}/application", headers=auth_headers, json={"status": "APPLIED"}
        )

        items = (await client.get(f"{API}/jobs", headers=auth_headers)).json()["items"]

        by_id = {item["id"]: item for item in items}
        assert by_id[alpha]["application"]["status"] == "APPLIED"
        assert by_id[alpha]["application"]["applied_at"] is not None
        assert len(items) == 2

    async def test_the_total_does_not_depend_on_who_is_asking(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The count query deliberately carries no join.
        job_id = await make_job(client, auth_headers)
        before = (await client.get(f"{API}/jobs", headers=auth_headers)).json()["total"]

        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        assert (await client.get(f"{API}/jobs", headers=auth_headers)).json()["total"] == before


class TestTheProfileLists:
    async def test_lists_what_was_saved_with_the_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job_id = await make_job(client, auth_headers, title="Data Engineer")
        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        body = (await client.get(f"{API}/applications", headers=auth_headers)).json()

        assert body["total"] == 1
        item = body["items"][0]
        assert item["status"] == "SAVED"
        # The row carries the job, so the profile page needs no second request.
        assert item["job"]["id"] == job_id
        assert item["job"]["title"] == "Data Engineer"
        # And not a second copy of itself nested inside its own job, which could
        # disagree with the outer one after the client updates it.
        assert item["job"]["application"] is None

    async def test_filters_by_status(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        saved = await make_job(client, auth_headers, title="Alpha Engineer")
        applied = await make_job(client, auth_headers, title="Beta Engineer")
        await client.put(f"{API}/jobs/{saved}/application", headers=auth_headers, json={})
        await client.put(
            f"{API}/jobs/{applied}/application", headers=auth_headers, json={"status": "APPLIED"}
        )

        only_applied = (
            await client.get(f"{API}/applications?status=APPLIED", headers=auth_headers)
        ).json()

        assert [item["job"]["id"] for item in only_applied["items"]] == [applied]
        # Unfiltered returns both, which is what the profile page asks for.
        both = (await client.get(f"{API}/applications", headers=auth_headers)).json()
        assert both["total"] == 2


class TestIsolationBetweenUsers:
    async def test_one_user_cannot_see_or_remove_another_s(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """No ownership check to get wrong, and no id to enumerate.

        The delete is scoped by (job_id, caller) in its WHERE clause, so it is
        structurally incapable of touching someone else's row — which sidesteps
        the 403-confirms-existence question entirely, because the client never
        holds an application id.
        """
        job_id = await make_job(client, auth_headers)
        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "other@example.com", "password": "correct-horse-9", "full_name": "O"},
        )
        other_headers = {
            "Authorization": f"Bearer {other.json()['tokens']['access_token']}"
        }

        listing = (await client.get(f"{API}/jobs", headers=other_headers)).json()
        assert listing["items"][0]["application"] is None
        theirs = await client.get(f"{API}/applications", headers=other_headers)
        assert theirs.json()["items"] == []

        removed = await client.delete(f"{API}/jobs/{job_id}/application", headers=other_headers)

        assert removed.status_code == 204
        # The other user's row is untouched.
        assert await live_rows(db_session, job_id) == 1


class TestDeletingAJobIsRestricted:
    async def test_a_saved_job_cannot_be_deleted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """RESTRICT, and it survives a soft delete.

        An application is historical fact, so removing a job must not silently
        cascade it away. The second half is the surprise worth pinning: a soft
        delete leaves the row and the foreign key, so unsaving does not free the
        job for deletion. Anything that needs to remove jobs — ADR-019's
        per-provider takedown path — has to delete applications first, and hard.
        """
        job_id = await make_job(client, auth_headers)
        await client.put(f"{API}/jobs/{job_id}/application", headers=auth_headers, json={})

        # Savepoints, not bare rollbacks: the fixture holds this whole test in
        # one transaction, and unwinding it would leak into later tests.
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text("DELETE FROM jobs WHERE id = :id"), {"id": job_id}
                )

        await client.delete(f"{API}/jobs/{job_id}/application", headers=auth_headers)

        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text("DELETE FROM jobs WHERE id = :id"), {"id": job_id}
                )
